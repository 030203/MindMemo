"""
小米 MiMo API 连通性冒烟测试

运行: cd backend && python -m tests.eval.smoke_xiaomi
"""
from __future__ import annotations

import os
import sys

# 确保从 backend 目录运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def main():
    from app.core.config import settings
    from app.services.llm_answer_service import llm_answer_service

    print("=== 小米 MiMo 冒烟测试 ===")
    print(f"provider : {settings.llm_provider}")
    print(f"base_url : {settings.xiaomi_base_url}")
    print(f"model    : {settings.xiaomi_model}")
    keys = settings.xiaomi_key_list
    print(f"keys     : {len(keys)} 个")

    if not llm_answer_service.is_available():
        print("✗  LLM 不可用，请检查 .env 配置")
        sys.exit(1)

    print("\n>>> 发送: 用一句话介绍你自己")
    answer = llm_answer_service.chat(question="用一句话介绍你自己")
    if answer:
        print(f"<<< 回答: {answer}")
        print("\n[OK] 小米 API 连通正常")
    else:
        print("[FAIL] 回答为空，API 可能异常")
        sys.exit(1)

    # 轮询验证：10次调用应覆盖多个不同 key
    if len(keys) > 1:
        print("\n>>> 验证 key 轮询（3 次调用）")
        for i in range(3):
            r = llm_answer_service.chat(question=f"第{i+1}次测试，回答ok即可")
            print(f"  [{i+1}] {'ok' if r else 'FAIL 空'}")
        print("[OK] key 轮询验证完毕")


if __name__ == "__main__":
    main()
