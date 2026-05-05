"""
Disaster Data Explorer – Streamlit UI
Interactive frontend for the EM-DAT 1900-2021 global disaster dataset.
Also serves as a live demo of every MCP tool exposed by server.py.
"""

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_service import (
    compute_statistics,
    df_to_records,
    filter_data,
    get_filter_options,
    load_data,
)

st.set_page_config(
    page_title="Disaster Data Explorer",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar filters ────────────────────────────────────────────────────────────

@st.cache_data
def cached_filter_options():
    return get_filter_options()


options = cached_filter_options()

st.sidebar.title("🔍 Filters")

year_min, year_max = options["year_range"]
year_range = st.sidebar.slider("Year range", year_min, year_max, (year_min, year_max))

continent = st.sidebar.selectbox(
    "Continent", ["All"] + options["continents"]
)

disaster_type = st.sidebar.selectbox(
    "Disaster type", ["All"] + options["disaster_types"]
)

country_input = st.sidebar.text_input("Country (partial match)", "")

# ── Apply filters ──────────────────────────────────────────────────────────────

@st.cache_data
def get_filtered(country, d_type, yr_from, yr_to, cont):
    return filter_data(
        country=country or None,
        disaster_type=None if d_type == "All" else d_type,
        year_from=yr_from,
        year_to=yr_to,
        continent=None if cont == "All" else cont,
    )


df = get_filtered(
    country_input,
    disaster_type,
    year_range[0],
    year_range[1],
    continent,
)

stats = compute_statistics(df)

# ── Header ────────────────────────────────────────────────────────────────────

st.title("🌍 Global Disaster Data Explorer")
st.caption(
    f"EM-DAT dataset · {options['year_range'][0]}–{options['year_range'][1]} · "
    f"{options['total_records']:,} total records"
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Events", f"{stats['total_events']:,}")
col2.metric("Total Deaths", f"{stats['total_deaths']:,}")
col3.metric("Total Affected", f"{stats['total_affected']:,}")
damages_b = stats["total_damages_000_usd"] / 1_000_000
col4.metric("Total Damages", f"${damages_b:.1f}B")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_overview, tab_table, tab_charts, tab_mcp = st.tabs(
    ["📊 Overview", "📋 Data Table", "📈 Charts", "🔧 MCP Tool Demo"]
)

# ──────────────────────────────────────────────────────────────────────────────
# TAB 1 · Overview
# ──────────────────────────────────────────────────────────────────────────────

with tab_overview:
    st.subheader("Events by Disaster Type")

    if stats["by_disaster_type"]:
        type_df = pd.DataFrame(stats["by_disaster_type"])
        fig = px.bar(
            type_df,
            x="type",
            y="total_deaths",
            color="total_deaths",
            color_continuous_scale="Reds",
            labels={"type": "Disaster Type", "total_deaths": "Total Deaths"},
        )
        fig.update_layout(coloraxis_showscale=False, xaxis_tickangle=-30)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Deaths by Continent")
    if stats["by_continent"]:
        cont_df = pd.DataFrame(stats["by_continent"])
        fig2 = px.pie(
            cont_df,
            names="continent",
            values="total_deaths",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        st.plotly_chart(fig2, use_container_width=True)

# ──────────────────────────────────────────────────────────────────────────────
# TAB 2 · Data Table
# ──────────────────────────────────────────────────────────────────────────────

with tab_table:
    display_cols = [
        "Year", "Country", "Continent", "Disaster Type", "Disaster Subtype",
        "Event Name", "Location",
        "Total Deaths", "Total Affected", "Total Damages ('000 US$)",
    ]
    available = [c for c in display_cols if c in df.columns]

    st.subheader(f"Showing {len(df):,} events")

    page_size = st.selectbox("Rows per page", [25, 50, 100], index=0)
    total_pages = max(1, (len(df) - 1) // page_size + 1)
    page = st.number_input("Page", min_value=1, max_value=total_pages, value=1) - 1

    start = page * page_size
    end = start + page_size
    st.dataframe(df[available].iloc[start:end], use_container_width=True)
    st.caption(f"Page {page + 1} of {total_pages}")

# ──────────────────────────────────────────────────────────────────────────────
# TAB 3 · Charts
# ──────────────────────────────────────────────────────────────────────────────

with tab_charts:
    st.subheader("Events & Deaths per Year")
    if stats["yearly_breakdown"]:
        yearly_df = pd.DataFrame(stats["yearly_breakdown"])
        fig3 = go.Figure()
        fig3.add_trace(
            go.Bar(x=yearly_df["Year"], y=yearly_df["events"], name="Events", opacity=0.6)
        )
        fig3.add_trace(
            go.Scatter(
                x=yearly_df["Year"],
                y=yearly_df["total_deaths"],
                name="Deaths",
                yaxis="y2",
                line=dict(color="red"),
            )
        )
        fig3.update_layout(
            yaxis=dict(title="Event Count"),
            yaxis2=dict(title="Total Deaths", overlaying="y", side="right"),
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig3, use_container_width=True)

    st.subheader("Top 15 Countries by Total Deaths")
    country_deaths = (
        df.groupby("Country")["Total Deaths"]
        .sum()
        .nlargest(15)
        .reset_index()
    )
    if not country_deaths.empty:
        fig4 = px.bar(
            country_deaths,
            x="Total Deaths",
            y="Country",
            orientation="h",
            color="Total Deaths",
            color_continuous_scale="Oranges",
        )
        fig4.update_layout(yaxis={"categoryorder": "total ascending"}, coloraxis_showscale=False)
        st.plotly_chart(fig4, use_container_width=True)

    st.subheader("Top 10 Deadliest Individual Events")
    top10 = df.nlargest(10, "Total Deaths")[
        ["Year", "Country", "Disaster Type", "Event Name", "Total Deaths"]
    ]
    st.dataframe(top10, use_container_width=True)

# ──────────────────────────────────────────────────────────────────────────────
# TAB 4 · MCP Tool Demo
# ──────────────────────────────────────────────────────────────────────────────

with tab_mcp:
    st.subheader("Live MCP Tool Tester")
    st.info(
        "This panel calls the same functions exposed by **server.py** — the MCP server "
        "you can connect to Claude Desktop or Claude Code. Results are returned as JSON, "
        "exactly as an LLM would receive them."
    )

    tool = st.selectbox(
        "Select MCP tool",
        [
            "query_disasters",
            "get_statistics",
            "get_top_disasters",
            "list_filter_options",
            "get_country_summary",
            "search_events",
        ],
    )

    # ── query_disasters ────────────────────────────────────────────────────────
    if tool == "query_disasters":
        c1, c2 = st.columns(2)
        t_country = c1.text_input("country", key="qd_country")
        t_type = c2.text_input("disaster_type", key="qd_type")
        c3, c4 = st.columns(2)
        t_yr_from = c3.number_input("year_from", value=1900, step=1, key="qd_yf")
        t_yr_to = c4.number_input("year_to", value=2021, step=1, key="qd_yt")
        c5, c6 = st.columns(2)
        t_limit = c5.number_input("limit", value=20, min_value=1, max_value=200, key="qd_lim")
        t_offset = c6.number_input("offset", value=0, min_value=0, key="qd_off")

        if st.button("Run tool", key="btn_qd"):
            result_df = filter_data(
                country=t_country or None,
                disaster_type=t_type or None,
                year_from=int(t_yr_from),
                year_to=int(t_yr_to),
            )
            total = len(result_df)
            page_df = result_df.iloc[int(t_offset): int(t_offset) + int(t_limit)]
            result = {
                "total_count": total,
                "offset": int(t_offset),
                "limit": int(t_limit),
                "records": df_to_records(page_df),
            }
            st.json(result)

    # ── get_statistics ─────────────────────────────────────────────────────────
    elif tool == "get_statistics":
        c1, c2 = st.columns(2)
        t_country = c1.text_input("country", key="gs_country")
        t_type = c2.text_input("disaster_type", key="gs_type")
        c3, c4 = st.columns(2)
        t_yr_from = c3.number_input("year_from", value=1900, step=1, key="gs_yf")
        t_yr_to = c4.number_input("year_to", value=2021, step=1, key="gs_yt")

        if st.button("Run tool", key="btn_gs"):
            result_df = filter_data(
                country=t_country or None,
                disaster_type=t_type or None,
                year_from=int(t_yr_from),
                year_to=int(t_yr_to),
            )
            st.json(compute_statistics(result_df))

    # ── get_top_disasters ──────────────────────────────────────────────────────
    elif tool == "get_top_disasters":
        c1, c2 = st.columns(2)
        t_metric = c1.selectbox("metric", ["deaths", "affected", "damages"], key="gtd_metric")
        t_n = c2.number_input("n", value=10, min_value=1, max_value=100, key="gtd_n")
        t_country = st.text_input("country (optional)", key="gtd_country")

        if st.button("Run tool", key="btn_gtd"):
            metric_map = {
                "deaths": "Total Deaths",
                "affected": "Total Affected",
                "damages": "Total Damages ('000 US$)",
            }
            col = metric_map[t_metric]
            result_df = filter_data(country=t_country or None)
            top = result_df.nlargest(int(t_n), col, keep="first")
            st.json({"metric": col, "top_n": int(t_n), "records": df_to_records(top)})

    # ── list_filter_options ────────────────────────────────────────────────────
    elif tool == "list_filter_options":
        if st.button("Run tool", key="btn_lfo"):
            st.json(get_filter_options())

    # ── get_country_summary ────────────────────────────────────────────────────
    elif tool == "get_country_summary":
        t_country = st.text_input("country", key="gcs_country")
        if st.button("Run tool", key="btn_gcs"):
            if not t_country:
                st.warning("Enter a country name.")
            else:
                result_df = filter_data(country=t_country)
                if result_df.empty:
                    st.json({"error": f"No records found for country matching '{t_country}'"})
                else:
                    result = compute_statistics(result_df)
                    result["matched_countries"] = sorted(result_df["Country"].dropna().unique().tolist())
                    result["query"] = t_country
                    st.json(result)

    # ── search_events ──────────────────────────────────────────────────────────
    elif tool == "search_events":
        t_query = st.text_input("query", key="se_query")
        c1, c2 = st.columns(2)
        t_limit = c1.number_input("limit", value=20, min_value=1, max_value=200, key="se_lim")
        t_offset = c2.number_input("offset", value=0, min_value=0, key="se_off")

        if st.button("Run tool", key="btn_se"):
            if not t_query:
                st.warning("Enter a search query.")
            else:
                result_df = filter_data(keyword=t_query)
                total = len(result_df)
                page_df = result_df.iloc[int(t_offset): int(t_offset) + int(t_limit)]
                st.json(
                    {
                        "query": t_query,
                        "total_count": total,
                        "offset": int(t_offset),
                        "limit": int(t_limit),
                        "records": df_to_records(page_df),
                    }
                )

    st.divider()
    st.subheader("MCP Server Connection")
    st.markdown(
        """
**Start the MCP server (streamable HTTP on port 8000):**
```bash
python server.py
# or on a custom port:
python server.py --port 9000
```

**Connect MCP Inspector:**
1. Open [MCP Inspector](https://modelcontextprotocol.io/inspector)
2. Transport → **Streamable HTTP**
3. URL → `http://localhost:8000/mcp`
4. Click **Connect**

**Add to Claude Desktop / Claude Code (`~/.claude/claude_desktop_config.json`):**
```json
{
  "mcpServers": {
    "disaster-data": {
      "command": "python",
      "args": ["/Users/albvs/storage/ai-architect/disaster-mcp/server.py"]
    }
  }
}
```
"""
    )
