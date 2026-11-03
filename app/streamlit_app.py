"""Quirky Analyst demo: ask a question, see the answer, SQL, table, chart and trace.

Run:  streamlit run app/streamlit_app.py
"""
import pandas as pd
import streamlit as st

from text2sql.agents import EXPERIMENTS, build_agent
from text2sql.config import load_settings
from text2sql.trace import Tracer

st.set_page_config(page_title="Quirky Analyst", layout="wide")


@st.cache_resource
def get_agent(name: str):
    return build_agent(name, load_settings(), tracer=Tracer())


def chart(df: pd.DataFrame) -> None:
    """Chart two-column results: a line for time series, bars for categories."""
    if df.shape[1] < 2 or len(df) < 2:
        return
    numeric = [c for c in df.columns[1:] if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric:
        return
    x, y = df.columns[0], numeric[-1]
    data = df[[x, y]].set_index(x)
    looks_like_time = pd.api.types.is_datetime64_any_dtype(df[x]) or any(
        w in str(x).lower() for w in ("month", "year", "day", "date", "week", "hour")
    )
    if looks_like_time:
        st.line_chart(data)
    elif len(df) <= 50:
        st.bar_chart(data)


st.title("Quirky Analyst")
st.caption("Ask a business question about the Olist Brazilian e-commerce data.")

with st.sidebar:
    agent_name = st.selectbox("Agent", list(EXPERIMENTS), index=0)
    st.caption("Only `baseline` is implemented so far.")

question = st.text_input("Question", placeholder="Which product categories earn the most revenue?")
if st.button("Ask", type="primary") and question.strip():
    try:
        agent = get_agent(agent_name)
        with st.spinner("Thinking..."):
            result = agent.answer(question.strip())
    except NotImplementedError as e:
        st.warning(str(e))
        st.stop()
    except Exception as e:  # noqa: BLE001 - show any setup/API error in the page
        st.error(f"{type(e).__name__}: {e}")
        st.stop()

    if result.text:
        st.markdown(result.text)
    if result.error:
        st.error(result.error)
    if result.sql:
        with st.expander("SQL"):
            st.code(result.sql, language="sql")
    if result.columns:
        df = pd.DataFrame(result.rows, columns=result.columns)
        if result.truncated:
            st.caption(f"Showing the first {len(df)} rows.")
        st.dataframe(df, width="stretch")
        chart(df)
    st.caption(f"{result.latency_s:.1f}s · {result.input_tokens + result.output_tokens:,} tokens · ${result.cost_usd:.4f}")
    with st.expander("Trace"):
        for step in result.steps:
            st.json(step, expanded=False)
