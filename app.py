import math
import pandas as pd
import requests
import streamlit as st

# Page setup
st.set_page_config(
    page_title="Soccer Bet Engine", layout="wide", initial_sidebar_state="expanded"
)

# --- SIDEBAR & API KEY SETUP ---
st.sidebar.title("Settings")
default_key = (
    st.secrets.get("ODDS_API_KEY", "") if "ODDS_API_KEY" in st.secrets else ""
)
api_key = st.sidebar.text_input(
    "The Odds API Key", value=default_key, type="password"
)

# --- HELPER FUNCTIONS ---


@st.cache_data(ttl=3600)
def get_all_soccer_sports(key):
  url = f"https://api.the-odds-api.com/v4/sports/?apiKey={key}"
  res = requests.get(url)
  if res.status_code == 200:
    sports = res.json()
    soccer_sports = [s["key"] for s in sports if s.get("group") == "Soccer"]
    rem_q = res.headers.get("x-requests-remaining", "N/A")
    used_q = res.headers.get("x-requests-used", "N/A")
    return soccer_sports, rem_q, used_q, None
  return [], "N/A", "N/A", f"API Error: HTTP {res.status_code}"


@st.cache_data(ttl=1800)
def fetch_soccer_odds(key, sports_tuple):
  all_fixtures = []
  region = "uk,eu"
  errors = []

  for sport in sports_tuple:
    markets = "h2h,totals,btts,team_totals"
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={key}&regions={region}&markets={markets}&oddsFormat=decimal"
    response = requests.get(url)

    if response.status_code == 200:
      all_fixtures.extend(response.json())
    elif response.status_code == 422:
      markets_fallback = "h2h,totals"
      url_fallback = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={key}&regions={region}&markets={markets_fallback}&oddsFormat=decimal"
      response_fb = requests.get(url_fallback)
      if response_fb.status_code == 200:
        all_fixtures.extend(response_fb.json())
      else:
        errors.append(
            f"{sport}: HTTP {response_fb.status_code} - {response_fb.text}"
        )
    else:
      errors.append(f"{sport}: HTTP {response.status_code} - {response.text}")

  return all_fixtures, errors


@st.cache_data(ttl=1800)
def fetch_player_props(key, sport, event_id):
  url = f"https://api.the-odds-api.com/v4/sports/{sport}/events/{event_id}/odds?apiKey={key}&regions=uk,eu&markets=player_anytime_goalscorer&oddsFormat=decimal"
  response = requests.get(url)
  if response.status_code == 200:
    return response.json()
  return None


# Poisson probability mass function
def poisson_prob(lmbda, k):
  return (lmbda**k * math.exp(-lmbda)) / math.factorial(k)


# Helper to convert UTC API time to SAST / CAT (UTC+2)
def format_kickoff_time(iso_string):
  dt = pd.to_datetime(iso_string)
  if dt.tzinfo is None:
    dt = dt.tz_localize("UTC")
  else:
    dt = dt.tz_convert("UTC")
  sast_dt = dt.tz_convert("Africa/Johannesburg")
  return sast_dt.strftime("%Y-%m-%d %H:%M") + " SAST"


# --- APP LAYOUT & TABS ---
st.title("⚽ Quantitative Soccer Betting Dashboard")

tab1, tab2, tab3 = st.tabs(
    ["Consensus Scanner", "Team/Match Specials", "Player Props"]
)

# ==========================================
# TAB 1: MATCH CONSENSUS SCANNER
# ==========================================
with tab1:
  st.subheader("Match Winner, Totals & BTTS Scanner")
  st.markdown(
      "Scans consensus market lines (**H2H**, **Over/Under 2.5**, and"
      " **BTTS**), de-vigs house margin, and checks **Prob Lock** and **+EV"
      " Edge** (Times in SAST/CAT)."
  )

  col_t1_a, col_t1_b = st.columns(2)
  with col_t1_a:
    prob_threshold_t1 = st.slider(
        "Probability 'Lock' Threshold (%)", 40, 80, 55, 5, key="prob_t1_slider"
    )
  with col_t1_b:
    ev_threshold_t1 = st.slider(
        "Minimum +EV Threshold (%)", 0.0, 10.0, 3.0, 0.5, key="ev_t1_slider"
    )

  if api_key:
    with st.spinner("Connecting to API and loading fixtures..."):
      leagues, remaining_quota, used_quota, error_msg = get_all_soccer_sports(
          api_key
      )

      st.sidebar.metric("API Quota Remaining", remaining_quota)
      st.sidebar.metric("API Requests Used", used_quota)

      if error_msg:
        st.error(error_msg)
      elif leagues:
        selected_leagues = st.multiselect(
            "Select Soccer Leagues to Scan:",
            options=leagues,
            default=leagues[:3],
            key="league_select",
        )

        if selected_leagues:
          data, api_errors = fetch_soccer_odds(api_key, tuple(selected_leagues))

          if api_errors:
            for err in api_errors:
              st.warning(f"API Warning: {err}")

          records = []
          extracted_fixtures = []

          for match in data:
            commence_time = format_kickoff_time(match.get("commence_time"))
            home = match.get("home_team")
            away = match.get("away_team")
            league = match.get("sport_title")
            match_id = match.get("id")
            sport_key = match.get("sport_key")
            match_name = f"{home} vs {away}"

            match_bookmakers = match.get("bookmakers", [])

            extracted_fixtures.append({
                "id": match_id,
                "sport": sport_key,
                "match": match_name,
                "home": home,
                "away": away,
                "bookmakers": match_bookmakers,
            })

            h2h_outcomes = {}
            totals_outcomes = {}
            btts_outcomes = {}

            for bookmaker in match_bookmakers:
              bk_name = bookmaker.get("title")
              for market in bookmaker.get("markets", []):
                key = market.get("key")

                if key == "h2h":
                  for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    price = outcome.get("price")
                    if name not in h2h_outcomes:
                      h2h_outcomes[name] = []
                    h2h_outcomes[name].append({"price": price, "bookie": bk_name})

                elif key == "totals":
                  for outcome in market.get("outcomes", []):
                    if outcome.get("point") == 2.5:
                      name = f"{outcome.get('name')} 2.5 Goals"
                      price = outcome.get("price")
                      if name not in totals_outcomes:
                        totals_outcomes[name] = []
                      totals_outcomes[name].append(
                          {"price": price, "bookie": bk_name}
                      )

                elif key == "btts":
                  for outcome in market.get("outcomes", []):
                    name = f"BTTS {outcome.get('name')}"
                    price = outcome.get("price")
                    if name not in btts_outcomes:
                      btts_outcomes[name] = []
                    btts_outcomes[name].append(
                        {"price": price, "bookie": bk_name}
                    )

            def process_market_dict(market_dict):
              if len(market_dict) >= 2:
                avg_implied_probs = {}
                best_prices = {}

                for name, odds_list in market_dict.items():
                  avg_odd = sum(o["price"] for o in odds_list) / len(odds_list)
                  avg_implied_probs[name] = 1.0 / avg_odd
                  best_prices[name] = max(
                      odds_list, key=lambda x: x["price"]
                  )

                total_margin = sum(avg_implied_probs.values())

                for name, best_data in best_prices.items():
                  true_prob = (
                      avg_implied_probs[name] / total_margin
                  ) * 100.0
                  best_odd = best_data["price"]
                  best_bookie = best_data["bookie"]

                  ev_edge = (
                      (((true_prob / 100.0) * best_odd) - 1.0) * 100.0
                  )

                  if name == "Draw":
                    label_name = "Match Draw"
                  elif "2.5 Goals" not in name and "BTTS" not in name:
                    label_name = f"{name} to Win"
                  else:
                    label_name = name

                  prob_lock = (
                      "🔒 LOCK" if true_prob >= prob_threshold_t1 else "⚠️ LEAVE"
                  )
                  value_signal = (
                      "🔒 +EV VALUE"
                      if ev_edge >= ev_threshold_t1
                      else "⚠️ NO VALUE"
                  )

                  records.append({
                      "Date & Time": commence_time,
                      "League": league,
                      "Match": match_name,
                      "Selection": label_name,
                      "Best Bookmaker": best_bookie,
                      "Best Odds": best_odd,
                      "Consensus Prob": f"{true_prob:.1f}%",
                      "Prob Lock": prob_lock,
                      "EV Edge": f"{ev_edge:+.1f}%",
                      "Value Signal": value_signal,
                  })

            process_market_dict(h2h_outcomes)
            process_market_dict(totals_outcomes)
            process_market_dict(btts_outcomes)

          st.session_state["live_fixtures"] = extracted_fixtures

          df = pd.DataFrame(records)
          if not df.empty:
            df = df.sort_values(
                by=["Value Signal", "Prob Lock"], ascending=[True, True]
            )

            lock_cnt = len(df[df["Prob Lock"] == "🔒 LOCK"])
            val_cnt = len(df[df["Value Signal"] == "🔒 +EV VALUE"])

            m1, m2 = st.columns(2)
            m1.metric("🔒 Probability Locks", lock_cnt)
            m2.metric("🔒 +EV Value Opportunities", val_cnt)

            st.write(f"### 📋 Scanned Market Lines ({len(df)} Options)")
            st.dataframe(df, use_container_width=True)
          else:
            st.warning(
                "No open bookmaker odds returned for the selected leagues."
            )
        else:
          st.info("Please select at least one league to scan.")
      else:
        st.warning("No active soccer leagues available right now.")
  else:
    st.info("Please enter your Odds API Key in the sidebar.")

# ==========================================
# TAB 2: TEAM & MATCH SPECIALS (Poisson Engine)
# ==========================================
with tab2:
  st.subheader("Team & Match Specials Poisson Engine")
  st.markdown(
      "Model match goal distributions using Expected Goals (xG) inputs to"
      " project core probabilities and team over 1.5 goal targets."
  )

  fixtures = st.session_state.get("live_fixtures", [])

  if fixtures:
    match_options = [f["match"] for f in fixtures]
    selected_match_name = st.selectbox(
        "Select Fixture for Poisson Modeling:",
        match_options,
        key="tab2_match_select",
    )

    selected_match_data = next(
        (f for f in fixtures if f["match"] == selected_match_name), None
    )

    if selected_match_data:
      home_team = selected_match_data["home"]
      away_team = selected_match_data["away"]
      match_bookmakers = selected_match_data.get("bookmakers", [])

      col_p1, col_p2 = st.columns(2)
      with col_p1:
        home_xg = st.slider(
            f"{home_team} Expected Goals (xG)",
            0.5,
            3.5,
            1.5,
            0.1,
            key="home_xg_slider",
        )
      with col_p2:
        away_xg = st.slider(
            f"{away_team} Expected Goals (xG)",
            0.3,
            3.0,
            1.1,
            0.1,
            key="away_xg_slider",
        )

      st.markdown("---")
      st.write("### ⚙️ Evaluation Thresholds")
      c_th1, c_th2 = st.columns(2)
      with c_th1:
        poisson_prob_thresh = st.slider(
            "Model Probability Lock Threshold (%)",
            40,
            85,
            55,
            5,
            key="poisson_prob_slider",
        )
      with c_th2:
        poisson_ev_thresh = st.slider(
            "Minimum +EV Edge Threshold (%)",
            0.0,
            10.0,
            2.0,
            0.5,
            key="poisson_ev_slider",
        )

      max_goals = 5
      home_probs = [poisson_prob(home_xg, i) for i in range(max_goals + 1)]
      away_probs = [poisson_prob(away_xg, j) for j in range(max_goals + 1)]

      home_win_prob = 0.0
      draw_prob = 0.0
      away_win_prob = 0.0
      btts_prob = 0.0
      over_25_prob = 0.0

      for h in range(max_goals + 1):
        for a in range(max_goals + 1):
          p = home_probs[h] * away_probs[a]

          if h > a:
            home_win_prob += p
          elif h == a:
            draw_prob += p
          else:
            away_win_prob += p

          if h > 0 and a > 0:
            btts_prob += p

          if (h + a) > 2.5:
            over_25_prob += p

      home_over_15_prob = (
          1.0 - home_probs[0] - home_probs[1]
      ) * 100.0
      away_over_15_prob = (
          1.0 - away_probs[0] - away_probs[1]
      ) * 100.0

      home_over_15_odds = []
      away_over_15_odds = []

      for bk in match_bookmakers:
        bk_name = bk.get("title")
        for market in bk.get("markets", []):
          if market.get("key") == "team_totals":
            for outcome in market.get("outcomes", []):
              if (
                  outcome.get("point") == 1.5
                  and outcome.get("name") == "Over"
              ):
                desc = outcome.get("description")
                price = outcome.get("price")
                if desc == home_team:
                  home_over_15_odds.append({"price": price, "bookie": bk_name})
                elif desc == away_team:
                  away_over_15_odds.append({"price": price, "bookie": bk_name})

      def evaluate_team_over_15(team_name, prob_val, odds_list):
        lock_status = (
            "🔒 LOCK" if prob_val >= poisson_prob_thresh else "⚠️ LEAVE"
        )
        if odds_list:
          best_item = max(odds_list, key=lambda x: x["price"])
          best_odd = best_item["price"]
          best_bookie = best_item["bookie"]
          ev_edge = (((prob_val / 100.0) * best_odd) - 1.0) * 100.0
          val_status = (
              "🔒 +EV VALUE" if ev_edge >= poisson_ev_thresh else "⚠️ NO VALUE"
          )
          return {
              "Team": team_name,
              "Model Prob": f"{prob_val:.1f}%",
              "Prob Lock": lock_status,
              "Best Bookmaker": best_bookie,
              "Best Odds": best_odd,
              "EV Edge": f"{ev_edge:+.1f}%",
              "Value Signal": val_status,
          }
        else:
          fair_odd = 1.0 / (prob_val / 100.0) if prob_val > 0 else 0.0
          return {
              "Team": team_name,
              "Model Prob": f"{prob_val:.1f}%",
              "Prob Lock": lock_status,
              "Best Bookmaker": "N/A (No Market Feed)",
              "Best Odds": round(fair_odd, 2),
              "EV Edge": "N/A",
              "Value Signal": "⚠️ NO ODDS FEED",
          }

      home_eval = evaluate_team_over_15(
          home_team, home_over_15_prob, home_over_15_odds
      )
      away_eval = evaluate_team_over_15(
          away_team, away_over_15_prob, away_over_15_odds
      )

      st.write("### 🎯 Team Over 1.5 Goals Analysis")
      team_over_df = pd.DataFrame([home_eval, away_eval])
      st.dataframe(team_over_df, use_container_width=True, hide_index=True)

      st.write("### 📊 Overall Match Model Probabilities")
      m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)
      m_col1.metric(f"{home_team} Win", f"{home_win_prob * 100:.1f}%")
      m_col2.metric("Draw", f"{draw_prob * 100:.1f}%")
      m_col3.metric(f"{away_team} Win", f"{away_win_prob * 100:.1f}%")
      m_col4.metric("BTTS Yes", f"{btts_prob * 100:.1f}%")
      m_col5.metric("Over 2.5 Goals", f"{over_25_prob * 100:.1f}%")

      st.write("### ⚽ Full Individual Team Goal Probabilities")
      t_col1, t_col2 = st.columns(2)

      with t_col1:
        st.write(f"**{home_team} Goal Breakdown**")
        home_goal_df = pd.DataFrame({
            "Goals": [
                f"{i} Goals" if i < max_goals else f"{max_goals}+ Goals"
                for i in range(max_goals + 1)
            ],
            "Probability": [f"{p * 100:.1f}%" for p in home_probs],
        })
        st.dataframe(home_goal_df, use_container_width=True, hide_index=True)

      with t_col2:
        st.write(f"**{away_team} Goal Breakdown**")
        away_goal_df = pd.DataFrame({
            "Goals": [
                f"{j} Goals" if j < max_goals else f"{max_goals}+ Goals"
                for j in range(max_goals + 1)
            ],
            "Probability": [f"{p * 100:.1f}%" for p in away_probs],
        })
        st.dataframe(away_goal_df, use_container_width=True, hide_index=True)
  else:
    st.info(
        "Please run a scan in **Tab 1** first to load active fixtures for"
        " modeling."
    )

# ==========================================
# TAB 3: PLAYER PROPS SCANNER
# ==========================================
with tab3:
  st.subheader("Player Props Scanner (Anytime Goalscorer)")
  st.markdown(
      "Scans player goalscoring prop markets for selected fixtures, comparing"
      " bookmaker odds to evaluate individual value."
  )

  fixtures = st.session_state.get("live_fixtures", [])

  if api_key and fixtures:
    prop_match_options = [f["match"] for f in fixtures]
    selected_prop_match = st.selectbox(
        "Select Fixture for Player Props:",
        prop_match_options,
        key="prop_match_sel",
    )

    prop_match_data = next(
        (f for f in fixtures if f["match"] == selected_prop_match), None
    )

    if prop_match_data and st.button("Scan Player Goalscorer Markets"):
      with st.spinner("Fetching player props from API..."):
        event_data = fetch_player_props(
            api_key, prop_match_data["sport"], prop_match_data["id"]
        )

        if event_data and "bookmakers" in event_data:
          prop_records = []
          for bookmaker in event_data.get("bookmakers", []):
            bk_name = bookmaker.get("title")
            for market in bookmaker.get("markets", []):
              if market.get("key") == "player_anytime_goalscorer":
                for outcome in market.get("outcomes", []):
                  player_name = outcome.get("description")
                  price = outcome.get("price")
                  prop_records.append({
                      "Player": player_name,
                      "Bookmaker": bk_name,
                      "Odds": price,
                      "Implied Prob": f"{(1.0 / price) * 100:.1f}%",
                  })

          df_props = pd.DataFrame(prop_records)
          if not df_props.empty:
            st.write(
                f"### 🎯 Anytime Goalscorer Odds ({len(df_props)} Markets"
                " Found)"
            )
            st.dataframe(df_props, use_container_width=True)
          else:
            st.warning(
                "No player prop markets currently available for this fixture"
                " from supported bookmakers."
            )
        else:
          st.warning(
              "Player prop markets are currently unavailable for this specific"
              " match or league."
          )
  elif not api_key:
    st.info("Please enter your Odds API Key in the sidebar.")
  else:
    st.info(
        "Please run a scan in **Tab 1** first to load fixtures for prop"
        " scanning."
    )
