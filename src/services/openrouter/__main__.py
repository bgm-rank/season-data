from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from .client import BgmCandidate, ChatRequest, MalBrief, Message, OpenRouterClient


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="OpenRouter LLM 动漫匹配测试")
    parser.add_argument(
        "mode",
        choices=["chat", "match"],
        help="chat: 自由对话; match: 动漫匹配测试",
    )
    parser.add_argument("--message", "-m", help="chat 模式下的用户消息")
    parser.add_argument("--mal-title", help="match 模式: MAL 标题")
    parser.add_argument("--mal-title-ja", help="match 模式: MAL 日文标题")
    parser.add_argument(
        "--candidates",
        help='match 模式: 候选列表, 格式 "id:name|name_cn,id:name|name_cn"',
    )
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("错误: 未设置 OPENROUTER_API_KEY 环境变量")
        return

    with OpenRouterClient(api_key) as client:
        if args.mode == "chat":
            if not args.message:
                print("错误: chat 模式需要 --message 参数")
                return
            request = ChatRequest(
                messages=[Message.user(args.message)],
            )
            response = client.chat(request)
            print(f"模型: {response.model}")
            print(f"回复: {response.content()}")
            print(
                f"Token: {response.usage.prompt_tokens} + "
                f"{response.usage.completion_tokens} = "
                f"{response.usage.total_tokens}"
            )

        elif args.mode == "match":
            if not args.mal_title or not args.candidates:
                print("错误: match 模式需要 --mal-title 和 --candidates 参数")
                return

            candidates: list[BgmCandidate] = []
            for item in args.candidates.split(","):
                id_rest = item.split(":", 1)
                bgm_id = int(id_rest[0])
                names = id_rest[1].split("|", 1) if len(id_rest) > 1 else [""]
                name = names[0]
                name_cn = names[1] if len(names) > 1 else None
                candidates.append(BgmCandidate(bgm_id=bgm_id, name=name, name_cn=name_cn))

            mal = MalBrief(title=args.mal_title, title_ja=args.mal_title_ja)
            results = client.match_anime(mal, candidates)
            if results:
                print(f"prompt 模式: {client.prompt_mode}")
                for r in results:
                    print(f"匹配结果: bgm_id={r['bgm_id']} confidence={r['confidence']} reason={r['reason']}")
            else:
                print("无匹配")


if __name__ == "__main__":
    main()
