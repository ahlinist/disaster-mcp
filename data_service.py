"""Shared data loading and querying layer for the disaster dataset."""

import os
import pandas as pd
from typing import Any, Dict, List, Optional

DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "1900_2021_DISASTERS.xlsx - emdat data.csv",
)

NUMERIC_COLS = [
    "Year", "Start Year", "End Year",
    "Total Deaths", "No Injured", "No Affected", "No Homeless", "Total Affected",
    "Insured Damages ('000 US$)", "Total Damages ('000 US$)", "CPI",
    "Dis Mag Value", "Latitude", "Longitude",
]

_df: Optional[pd.DataFrame] = None


def load_data() -> pd.DataFrame:
    global _df
    if _df is None:
        _df = pd.read_csv(DATA_PATH, low_memory=False)
        for col in NUMERIC_COLS:
            if col in _df.columns:
                _df[col] = pd.to_numeric(_df[col], errors="coerce")
    return _df


def filter_data(
    country: Optional[str] = None,
    disaster_type: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    continent: Optional[str] = None,
    disaster_subgroup: Optional[str] = None,
    keyword: Optional[str] = None,
) -> pd.DataFrame:
    df = load_data()

    if country:
        df = df[df["Country"].str.contains(country, case=False, na=False)]
    if disaster_type:
        df = df[df["Disaster Type"].str.contains(disaster_type, case=False, na=False)]
    if year_from is not None:
        df = df[df["Year"] >= year_from]
    if year_to is not None:
        df = df[df["Year"] <= year_to]
    if continent:
        df = df[df["Continent"].str.contains(continent, case=False, na=False)]
    if disaster_subgroup:
        df = df[df["Disaster Subgroup"].str.contains(disaster_subgroup, case=False, na=False)]
    if keyword:
        mask = (
            df["Event Name"].str.contains(keyword, case=False, na=False)
            | df["Location"].str.contains(keyword, case=False, na=False)
            | df["Country"].str.contains(keyword, case=False, na=False)
        )
        df = df[mask]

    return df


def df_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Convert DataFrame slice to clean JSON-serialisable records."""
    return [
        {k: (None if pd.isna(v) else v) for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]


def get_filter_options() -> Dict[str, Any]:
    df = load_data()
    return {
        "countries": sorted(df["Country"].dropna().unique().tolist()),
        "disaster_types": sorted(df["Disaster Type"].dropna().unique().tolist()),
        "disaster_subgroups": sorted(df["Disaster Subgroup"].dropna().unique().tolist()),
        "continents": sorted(df["Continent"].dropna().unique().tolist()),
        "year_range": [int(df["Year"].min()), int(df["Year"].max())],
        "total_records": len(df),
    }


def compute_statistics(df: pd.DataFrame) -> Dict[str, Any]:
    total = len(df)
    deaths = int(df["Total Deaths"].sum(skipna=True))
    affected = int(df["Total Affected"].sum(skipna=True))
    damages = float(df["Total Damages ('000 US$)"].sum(skipna=True))

    by_type = (
        df.groupby("Disaster Type")["Total Deaths"]
        .agg(events="count", total_deaths="sum")
        .reset_index()
        .rename(columns={"Disaster Type": "type"})
        .sort_values("total_deaths", ascending=False)
        .head(20)
        .to_dict(orient="records")
    )

    by_continent = (
        df.groupby("Continent")["Total Deaths"]
        .agg(events="count", total_deaths="sum")
        .reset_index()
        .rename(columns={"Continent": "continent"})
        .sort_values("total_deaths", ascending=False)
        .to_dict(orient="records")
    )

    yearly = (
        df.groupby("Year")
        .agg(events=("Year", "count"), total_deaths=("Total Deaths", "sum"))
        .reset_index()
        .sort_values("Year")
        .to_dict(orient="records")
    )

    return {
        "total_events": total,
        "total_deaths": deaths,
        "total_affected": affected,
        "total_damages_000_usd": round(damages, 2),
        "by_disaster_type": by_type,
        "by_continent": by_continent,
        "yearly_breakdown": yearly,
    }
