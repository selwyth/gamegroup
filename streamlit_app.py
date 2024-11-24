import numpy as np
import pandas as pd
import streamlit as st
import yaml

from boardgamegeek import BGGClient
from boardgamegeek.cache import CacheBackendMemory
from streamlit_gsheets import GSheetsConnection

st.title("Game Group Analyzer")
with open("groups.yaml", "r") as f:
    group_data = yaml.safe_load(f)

GROUP = st.selectbox("Select group", options=group_data.keys())
USER_DISPLAY_FIELD = st.selectbox("Choose how to display the user (default is BGG handle)",
                                  [""] + group_data[GROUP]["user_display_fields"],
                                  format_func=lambda x: x.title())
USER_DISPLAY_FIELD2 = "user" if USER_DISPLAY_FIELD == "" else USER_DISPLAY_FIELD
conn = st.connection(group_data[GROUP]["connection"], type=GSheetsConnection)

if st.button("Refresh the cached data from BGG -- use sparingly!"):
    bgg = BGGClient(cache=CacheBackendMemory(ttl=10),
                    retries=10, retry_delay=10)
    result = []
    for u in group_data[GROUP]["users"]:
        user = list(u.keys())[0]
        with st.spinner(f"Refreshing {user}"):
            coll = bgg.collection(user)
            for game in coll:
                record = dict(
                    user=user,
                    boardgame=game.name,
                    gameid=game.id,
                    rating=game.rating,
                    owned=game.owned,
                    for_trade=game.for_trade,
                    preordered=game.preordered,
                    want=game.want,
                    want_to_buy=game.want_to_buy,
                    want_to_play=game.want_to_play,
                    wishlist=game.wishlist,
                )
                result.append(record)

    df = pd.DataFrame(result)
    
    conn.update(worksheet="Sheet1", data=df)

try:
    df = conn.read(worksheet="Sheet1")
except:
    st.warning("Unable to load cache. Try refreshing the cache?")

if USER_DISPLAY_FIELD != "":
    mapping = {k:v[USER_DISPLAY_FIELD] for d in group_data[GROUP]["users"] for k, v in d.items()}
    df[USER_DISPLAY_FIELD] = df.user.map(mapping)

st.subheader("Most Want to Play")
col1, col2 = st.columns(2)
OWNED_IS_WTP = col1.checkbox("Treat Owned as Want-to-Play?", value=True)
WANT_IS_WTP = col2.checkbox("Treat Wishlist/Preordered as Want-to-Play?", value=True)
SUBSET = st.multiselect("Choose a subset of users in the group",
                        options=df[USER_DISPLAY_FIELD2].sort_values().unique())

if len(SUBSET) > 0:
    df = df.loc[df[USER_DISPLAY_FIELD].isin(SUBSET)]

bool_cols = [
    "owned",
    "for_trade",
    "preordered",
    "want",
    "want_to_buy",
    "want_to_play",
    "wishlist",
]
for bc in bool_cols:
    df[bc] = df[bc].astype(int)  # sometimes the result is bool, sometimes it's int
    df[bc + "_bool"] = df[bc].astype(bool)

df = df.assign(
    wtp = (
        df.want_to_play_bool
        + (OWNED_IS_WTP * df.owned_bool)
        + (WANT_IS_WTP * (df.want_bool + df.wishlist_bool + df.preordered_bool + df.want_to_buy_bool))
        + ((df.user == "selwyth") * (df.owned_bool))  # :)
    ).astype(int),
)

remote_mapping = {k:v.get("remote", False) for d in group_data[GROUP]["users"] for k, v in d.items()}
df["remote"] = df.user.map(remote_mapping)
wtp_summary = (
    df.loc[~df.remote]
    .groupby(["gameid"])
    .agg(
        boardgame = ("boardgame", pd.Series.mode),
        want_to_play = ("wtp", "sum"),
        num_owners = ("owned", "sum"),
    )
    .sort_values("want_to_play", ascending=False)
)
wtp = df.loc[(df.wtp == 1) & ~(df.remote)].groupby("gameid")[USER_DISPLAY_FIELD2].apply(list)
wtp.name = "Who wants to play?"
owners = df.loc[(df.owned_bool) & ~(df.remote)].groupby("gameid")[USER_DISPLAY_FIELD2].apply(list)
owners.name = "Who owns?"
wtp_summary2 = wtp_summary.join(wtp).join(owners)

def highlight_row(row):
    if row["num_owners"] == 0:
        return ["background-color: salmon"] * len(row)
    else:
        return [""] * len(row)

s = wtp_summary2.style.apply(
    highlight_row,
    axis=1,
)

st.data_editor(s, column_config={
    "Who owns?": st.column_config.ListColumn("Who owns?")
})

st.subheader("Ratings")
r = (
    df.groupby(["gameid", "user"])["rating"]
    .max()
    .unstack()
    .fillna(df.groupby("user")["rating"].mean())
    .mean(1)
)
r.name = "adjusted_rating"

s = df.groupby("gameid").agg(
    boardgame = ("boardgame", pd.Series.mode),
    raw_rating = ("rating", "mean"),
    num_ratings = ("rating", "count"),
).join(r)
st.data_editor(s.sort_values("adjusted_rating", ascending=False),
             column_config={
                 "raw_rating": st.column_config.NumberColumn("Avg Rating", format="%.2f"),
                 "num_ratings": st.column_config.NumberColumn("# Raters"),
                 "adjusted_rating": st.column_config.NumberColumn("Adj. Rating", format="%.2f"),
             })

st.subheader("Trades")
t = (
    df.loc[~(df.remote) & (df.for_trade == 1)]
    .groupby("gameid")
    [USER_DISPLAY_FIELD2]
    .apply(list)
)
t.name = "Who's Trading?"
w = (
    df.loc[~(df.remote) & (df.want == 1)]
    .groupby("gameid")
    [USER_DISPLAY_FIELD2]
    .apply(list)
)
w.name = "Who Wants?"
t2 = t.to_frame().join(w, how="inner")
t2["boardgame"] = s["boardgame"]
t2 = t2.loc[(t2["Who's Trading?"].notnull()) & (t2["Who Wants?"].notnull())]  # Covers edge case of no matches
st.data_editor(t2.set_index("boardgame"))

st.subheader("Most Wanted")
w = (
    df.loc[df.want == 1]
      .groupby("gameid")
      .agg(
          boardgame = ("boardgame", pd.Series.mode),
          num_wishlists = ("user", "nunique"),
          who_wants = ("user", list),
      )
      .sort_values("num_wishlists", ascending=False)
)
st.data_editor(w.set_index("boardgame"), use_container_width=True)