"""1.8: post-chat survey on (optional) with the default questions, and the feedback alert rules."""


def execute():
    from thinknxg_support.install import ensure_agent_tool_defaults, ensure_feedback_defaults

    ensure_agent_tool_defaults()
    ensure_feedback_defaults()
