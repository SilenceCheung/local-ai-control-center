"""Fixed benchmark prompts. temperature=0, fixed max_tokens — results are
comparable across runs and across Safe/Fast modes."""

BENCHMARK_PROMPTS: dict[str, dict] = {
    "coding_short": {
        "label": "Coding · Short",
        "max_tokens": 256,
        "prompt": "Write a Python function that parses an ISO-8601 timestamp string and "
                  "returns a timezone-aware datetime. Include error handling and a docstring.",
    },
    "coding_long": {
        "label": "Coding · Long",
        "max_tokens": 1024,
        "prompt": "Create a production-ready SwiftUI macOS application feature that includes "
                  "file browsing, search, sorting, context menus, drag and drop, keyboard "
                  "shortcuts, error handling, and tests.",
    },
    "agent_tool_use": {
        "label": "Agent · Tool Use",
        "max_tokens": 512,
        "prompt": "You have tools: read_file(path), search(query), edit_file(path, old, new), "
                  "run_terminal(cmd). A Python project's tests fail with "
                  "'ImportError: cannot import name UserService from app.services'. "
                  "Plan and describe the exact sequence of tool calls you would make to "
                  "diagnose and fix this, with concrete arguments for each call.",
    },
    "chinese_reasoning": {
        "label": "Chinese · Reasoning",
        "max_tokens": 512,
        "prompt": "一个仓库有三种袋子：大袋每袋装 12 件，中袋每袋装 8 件，小袋每袋装 5 件。"
                  "现在要正好装 100 件商品，且大袋数量必须是中袋数量的两倍，小袋至少用 1 个。"
                  "请一步步推理，给出所有可行的组合。",
    },
    "long_context": {
        "label": "Long Context",
        "max_tokens": 512,
        "prompt_builder": "long_context",  # built at runtime: ~8k token document + question
    },
}


def build_long_context_prompt(target_tokens: int = 8000) -> str:
    """Deterministic synthetic long document + retrieval question."""
    sections = []
    for i in range(1, 200):
        sections.append(
            f"Section {i}: Service unit {i} reports nominal operation. "
            f"Throughput index {i * 7 % 97}, error budget {i * 13 % 51} percent remaining, "
            f"owner team 'platform-{i % 12}'."
        )
        if i == 137:
            sections.append(
                "Section 137-NOTE: The rollback key for the payment cluster is 'AMBER-COBALT-9241'."
            )
    doc = "\n".join(sections)
    words = doc.split()
    approx_words = int(target_tokens / 1.35)
    doc = " ".join(words[:approx_words])
    return (
        f"Read the following operations report carefully.\n\n{doc}\n\n"
        "Question: What is the rollback key for the payment cluster mentioned in the report? "
        "Answer with the key only."
    )
