"""Judge-facing Streamlit application for the frozen synthetic ACME demonstration."""

from __future__ import annotations

import streamlit as st

from institutional_risk_fleet.cloud_config import CloudConfig
from institutional_risk_fleet.domain import HumanAction, HumanReviewStatus
from institutional_risk_fleet.ui_service import (
    DecisionInputError,
    DemoApplication,
    GeminiUnavailableError,
    configured_demo_application,
    gemini_availability,
)

st.set_page_config(
    page_title="Institutional Risk Agent Fleet",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.8rem; padding-bottom: 3rem; max-width: 1180px;}
    .synthetic-banner {letter-spacing: .12em; font-weight: 700; color: #8a5800;
        background: #fff4d6; border-left: 4px solid #e0a11a; padding: .55rem .8rem;
        margin: .25rem 0 1.25rem 0;}
    .eyebrow {letter-spacing: .08em; text-transform: uppercase; color: #667085;
        font-size: .78rem; font-weight: 650;}
    .status-line {padding: .65rem .85rem; background: rgba(49, 51, 63, .06);
        border-left: 3px solid #5a6575; margin-bottom: .5rem;}
    .control-note {color: #475467; font-size: .88rem;}
    .environment-badge {display: inline-block; padding: .2rem .55rem; border-radius: 999px;
        background: rgba(49, 51, 63, .08); color: #475467; font-size: .76rem; font-weight: 650;}
    div[data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
    </style>
    """,
    unsafe_allow_html=True,
)


config = CloudConfig.from_env()


def _service() -> DemoApplication:
    if "demo_application" not in st.session_state:
        st.session_state.demo_application = configured_demo_application(config)
    return st.session_state.demo_application


service = _service()

with st.sidebar:
    st.header("Demo controls")
    st.markdown(
        f'<span class="environment-badge">{config.environment_label}</span>',
        unsafe_allow_html=True,
    )
    provider_options = ("offline", "gemini")
    provider = st.radio(
        "Reasoning provider",
        provider_options,
        index=provider_options.index(service.provider_name),
        format_func=lambda item: "Offline — reproducible" if item == "offline" else "Gemini + ADK",
        disabled=service.triggered or config.app_env == "cloud",
        help="Reset the demo before changing provider after an investigation starts.",
    )
    allow_fallback = st.checkbox(
        "Allow labeled offline fallback",
        value=service.deterministic_fallback,
        disabled=service.triggered or provider != "gemini" or config.app_env == "cloud",
        help="Never enabled silently. Gemini failures otherwise escalate to human review.",
    )
    if config.app_env == "local" and not service.triggered and (
        provider != service.provider_name
        or allow_fallback != service.deterministic_fallback
    ):
        service = DemoApplication(
            provider_name=provider,
            deterministic_fallback=allow_fallback,
        )
        st.session_state.demo_application = service

    availability = gemini_availability()
    if provider == "gemini" and config.app_env == "cloud":
        st.success("Gemini uses the worker service identity through Vertex AI.")
    elif provider == "gemini":
        if availability.available:
            st.success(availability.reason)
        else:
            st.warning(f"Gemini unavailable: {availability.reason}")
    else:
        st.caption("No model credentials required.")

    st.divider()
    if st.button("Reset Demo", type="secondary", width="stretch"):
        try:
            service.reset()
            for key in ("reviewer", "rationale", "human_action"):
                st.session_state.pop(key, None)
            st.rerun()
        except RuntimeError as error:
            st.error(str(error))

    st.subheader("Governance controls")
    st.markdown(
        """
        - Scoped agent permissions
        - Deterministic financial tools
        - Required evidence lineage
        - Structured numeric verification
        - Immutable claim versioning
        - Ordered audit trail
        - Explicit human gate
        """
    )
    st.caption("Controls are enforced in application code, not UI configuration or prompts.")

st.title("Institutional Risk Agent Fleet")
st.markdown(
    '<div class="synthetic-banner">SYNTHETIC DEMO DATA · NOT INVESTMENT ADVICE</div>',
    unsafe_allow_html=True,
)

portfolio_tab, investigation_tab, verification_tab, decision_tab = st.tabs(
    ["Portfolio", "Investigation", "Evidence & Verification", "Decision"]
)

with portfolio_tab:
    portfolio = service.portfolio_view()
    st.markdown('<div class="eyebrow">Autonomous risk event</div>', unsafe_allow_html=True)
    st.header("ACME Corp spread shock")
    metric_columns = st.columns(4)
    metric_columns[0].metric("Portfolio exposure", f"${portfolio.exposure_usd / 1_000_000:.0f}m")
    metric_columns[1].metric(
        "Spread",
        f"{portfolio.current_spread_bps:.0f} bp",
        delta=f"+{portfolio.spread_move_bps:.0f} bp",
        delta_color="inverse",
    )
    metric_columns[2].metric("Previous spread", f"{portfolio.previous_spread_bps:.0f} bp")
    metric_columns[3].metric("Severity", portfolio.severity)
    st.markdown(
        f'<div class="status-line"><strong>Lifecycle:</strong> {portfolio.lifecycle} &nbsp;·&nbsp; '
        f'<strong>Governance:</strong> {portfolio.governance}</div>',
        unsafe_allow_html=True,
    )
    trigger_disabled = service.triggered or (
        config.app_env == "local" and provider == "gemini" and not availability.available
    )
    if st.button(
        "Trigger Risk Event",
        type="primary",
        disabled=trigger_disabled,
        help="Starts the complete workflow; individual agents are never triggered manually.",
    ):
        try:
            with st.spinner("Publishing event and polling the governed investigation…"):
                service.trigger()
            st.success("Risk event processed through the configured event path.")
            st.rerun()
        except (GeminiUnavailableError, RuntimeError) as error:
            st.error(str(error))
    if service.triggered:
        st.success("Risk event processed once. Reruns will reuse the authoritative investigation.")
    elif trigger_disabled:
        st.info("Select Offline or configure Gemini credentials to trigger the event.")

    with st.expander("Synthetic portfolio context"):
        st.table(
            [
                {
                    "Issuer": row.issuer,
                    "Market value": f"${row.market_value_usd / 1_000_000:.0f}m",
                    "Spread duration": f"{row.spread_duration:.1f}",
                }
                for row in portfolio.positions
            ]
        )

with investigation_tab:
    view = service.investigation_view()
    st.markdown('<div class="eyebrow">Autonomous orchestration</div>', unsafe_allow_html=True)
    st.header("One event, governed fleet response")
    if view is None:
        st.info("Trigger the ACME risk event from Portfolio to start the investigation.")
    else:
        st.caption(f"Reasoning: {view.reasoning_label}")
        for item in view.progress:
            with st.container(border=True):
                name, status = st.columns([3, 1])
                name.markdown(f"**{item.label}**  \n{item.execution_type}")
                status.markdown(f"**{item.status.replace('_', ' ')}**")
                st.caption(item.result)

        st.subheader("Current architecture")
        st.graphviz_chart(
            """
            digraph Fleet {
              rankdir=TB;
              graph [bgcolor="transparent", pad="0.2", nodesep="0.3", ranksep="0.35"];
              node [shape=box, style="rounded,filled", fillcolor="#F4F6F8", color="#98A2B3", fontname="Arial"];
              edge [color="#667085"];
              event [label="Synthetic Event"];
              workflow [label="Deterministic Workflow"];
              evidence [label="Evidence + Tools"];
              credit [label="Credit"];
              market [label="Market"];
              investigator [label="Investigator"];
              challenger [label="Challenger"];
              adapter [label="Validated Adapter"];
              verifier [label="Deterministic Verifier"];
              governance [label="Governance Engine"];
              human [label="Human Gate"];
              event -> workflow -> evidence;
              evidence -> credit; evidence -> market;
              credit -> investigator; market -> investigator;
              investigator -> challenger -> adapter -> verifier -> governance -> human;
            }
            """,
            width="stretch",
        )
        st.caption(
            "Google ADK coordinates reasoning roles. Evidence, tools, adapter validation, "
            "verification, governance, and the human gate remain deterministic Python controls."
        )

with verification_tab:
    verification = service.verification_view()
    st.markdown('<div class="eyebrow">The control moment</div>', unsafe_allow_html=True)
    st.header("The system preserved and corrected a material error")
    if verification is None:
        st.info("Verification evidence appears after the risk event is triggered.")
    else:
        original_col, arrow_col, revised_col = st.columns([5, 1, 5], vertical_alignment="center")
        with original_col:
            if verification.rejected_claim:
                st.error(
                    f"REJECTED · {verification.rejected_claim.claim_id}\n\n"
                    f"**FY2025 leverage = {verification.rejected_claim.value}"
                    f"{verification.rejected_claim.unit}**"
                )
                st.caption("Original claim remains in immutable history.")
            else:
                st.info("Gemini did not submit the conflicting 4.1x claim in this run.")
        arrow_col.markdown("## →")
        with revised_col:
            if verification.revised_claim:
                st.success(
                    f"VERIFIED · {verification.revised_claim.claim_id}\n\n"
                    f"**FY2025 leverage = {verification.revised_claim.value}"
                    f"{verification.revised_claim.unit}**"
                )
                if verification.revised_claim.supersedes_claim_id:
                    st.caption(
                        f"Supersedes {verification.revised_claim.supersedes_claim_id}; original retained."
                    )
            else:
                st.warning("No verified leverage revision is available.")

        st.subheader("Why 4.1x failed")
        st.table(
            [
                {
                    "Source": support.label,
                    "Value": f"{support.value}{support.unit}",
                    "Authority": "Authoritative" if support.authoritative else "Non-authoritative",
                    "Lineage": support.reference_id,
                }
                for support in verification.support_values
            ]
        )
        if verification.failure_rationale:
            st.error(f"FAILED — numeric discrepancy. {verification.failure_rationale}")

        st.subheader("Permission boundary")
        if verification.permission_denial:
            denial = verification.permission_denial
            st.error(
                f"Credit Agent requested portfolio-position access — DENIED\n\n"
                f"{denial.rationale} · audit sequence {denial.sequence}"
            )

        st.subheader("Ordered audit timeline")
        timeline = service.audit_timeline()
        st.dataframe(
            [
                {
                    "Seq": item.sequence,
                    "Actor": item.actor,
                    "Event": item.event_type,
                    "What happened": item.summary,
                }
                for item in timeline
            ],
            hide_index=True,
            width="stretch",
        )
        with st.expander("Full audit trace"):
            st.dataframe(
                [item.model_dump() for item in service.audit_timeline(full=True)],
                hide_index=True,
                width="stretch",
            )

with decision_tab:
    decision = service.decision_view()
    st.markdown('<div class="eyebrow">Human authority</div>', unsafe_allow_html=True)
    st.header("Machine clearance is not autonomous approval")
    if decision is None:
        st.info("Decision controls appear after the investigation completes.")
    else:
        decision_columns = st.columns(4)
        decision_columns[0].metric("Machine verification", decision.machine_verification)
        decision_columns[1].metric("Risk classification", decision.risk_classification)
        decision_columns[2].metric(
            "Governance status", decision.governance_status.replace("_", " ")
        )
        decision_columns[3].metric(
            "Human review", decision.human_review_status.replace("_", " ")
        )
        st.caption(f"Lifecycle: {decision.lifecycle_status.replace('_', ' ')}")

        if decision.recommendation:
            st.subheader("Investigator recommendation")
            st.info(decision.recommendation)
            with st.expander("Verified supporting premises"):
                for premise in decision.supporting_premises:
                    st.markdown(f"- {premise}")

        current = service.current_investigation()
        can_decide = bool(
            current
            and current.human_review_status == HumanReviewStatus.REQUIRED
            and not current.human_decisions
        )
        if decision.decision_recorded:
            latest = current.human_decisions[-1] if current else None
            st.success(
                f"Human decision recorded: {latest.action.value if latest else 'RECORDED'}. "
                f"Lifecycle is now {decision.lifecycle_status}."
            )
        else:
            with st.form("human_decision_form", clear_on_submit=False):
                action = st.radio(
                    "Decision",
                    tuple(HumanAction),
                    format_func=lambda item: item.value.replace("_", " "),
                    horizontal=True,
                    key="human_action",
                    disabled=not can_decide,
                )
                reviewer = st.text_input(
                    "Reviewer identity", key="reviewer", disabled=not can_decide
                )
                rationale = st.text_area(
                    "Rationale", key="rationale", disabled=not can_decide
                )
                submitted = st.form_submit_button(
                    "Record Human Decision",
                    type="primary",
                    disabled=not can_decide,
                )
                if submitted:
                    try:
                        service.record_human_decision(
                            action=action,
                            reviewer=reviewer,
                            rationale=rationale,
                        )
                        st.rerun()
                    except DecisionInputError as error:
                        st.error(str(error))

        if decision.human_review_status == HumanReviewStatus.MORE_INVESTIGATION.value:
            st.warning("More investigation requested. The lifecycle has returned to INVESTIGATING.")
