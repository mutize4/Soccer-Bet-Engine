import streamlit as st
import requests
import pandas as pd
import math
from thefuzz import process, fuzz

st.set_page_config(page_title="Soccer Best Bet Engine", layout="wide")
st.title("⚽ Soccer Best Bet & Recommendation Engine")

# Initialize session state for real fixtures
if "live_fixtures" not in st.session_state:
    st.session_state["live_fixtures"] = []

# --- SIDEBAR CONTROLS ---
st.sidebar.header("Settings & Quota")

raw_api_key = st.sidebar.text_input("The Odds API Key", type="password")
api_key = raw_api_key.strip() if raw_api_key else ""

if st.sidebar.button("🔄 Clear App Cache"):
    st.cache_data.clear()
    st.session_state["live_fixtures"] = []
    st.rerun()

# --- HELPER FUNCTIONS ---
def get_all_soccer_sports(key):
    url = f"https://api.the-odds-api.com/v4/sports/?apiKey={key}"
    response = requests.get(url)
    
    remaining = response.headers.get("x-requests-remaining", "Unknown")
    used = response.headers.get("x-requests-used", "Unknown")
    
    if response.status_code == 200:
        res = response.json()
        leagues = [sport['key'] for sport in res if sport.get('group') == 'Soccer']
        return leagues, remaining, used, None
    elif response.status_code == 401:
        return [], 0, 0, "Unauthorized: The API key was rejected."
    elif response.status_code == 429:
        return [], 0, 0, "Quota Exceeded: You have used up your free monthly requests."
    else:
        return [], remaining, used, f"API Error HTTP {response.status_code}: {response.text}"

@st.cache_data(ttl=1800)
def fetch_soccer_odds(key, sports_tuple):
    all_fixtures = []
    markets = "h2h,totals"
    region = "uk,eu" 
    errors = []
    
    for sport in sports_tuple:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={key}&regions={region}&markets={markets}&oddsFormat=decimal"
        response = requests.get(url)
        if response.status_code == 200:
            all_fixtures.extend(response.json())
        else:
            errors.append(f"{sport}: HTTP {response.status_code} - {response.text}")
            
    return all_fixtures, errors

# --- TABS LAYOUT ---
tab1, tab2, tab3 = st.tabs([
    "📊 Match Consensus Scanner", 
    "📐 Team & Match Specials (+EV)", 
    "🎯 Player Props (+EV Engine)"
])

# ==========================================
# TAB 1: MATCH CONSENSUS SCANNER
# ==========================================
with tab1:
    st.subheader("Match Winner & Totals Scanner")
    st.markdown("Scans consensus market lines, de-vigs house margin, and checks both **Win Probability Lock** and **+EV Edge**.")
    
    col_t1_a, col_t1_b = st.columns(2)
    with col_t1_a:
        prob_threshold_t1 = st.slider("Probability 'Lock' Threshold (%)", 40, 80, 55, 5, key="prob_t1_slider")
    with col_t1_b:
        ev_threshold_t1 = st.slider("Minimum +EV Threshold (%)", 0.0, 10.0, 3.0, 0.5, key="ev_t1_slider")

    if api_key:
        with st.spinner("Connecting to API and loading fixtures..."):
            leagues, remaining_quota, used_quota, error_msg = get_all_soccer_sports(api_key)
            
            st.sidebar.metric("API Quota Remaining", remaining_quota)
            st.sidebar.metric("API Requests Used", used_quota)
            
            if error_msg:
                st.error(error_msg)
            elif leagues:
                selected_leagues = st.multiselect(
                    "Select Soccer Leagues to Scan:",
                    options=leagues,
                    default=leagues[:3],
                    key="league_select"
                )
                
                if selected_leagues:
                    data, api_errors = fetch_soccer_odds(api_key, tuple(selected_leagues))
                    
                    if api_errors:
                        for err in api_errors:
                            st.warning(f"API Warning: {err}")
                    
                    records = []
                    extracted_fixtures = []
                    
                    for match in data:
                        commence_time = pd.to_datetime(match.get('commence_time')).strftime('%Y-%m-%d %H:%M')
                        home = match.get('home_team')
                        away = match.get('away_team')
                        league = match.get('sport_title')
                        match_name = f"{home} vs {away}"
                        
                        extracted_fixtures.append({"match": match_name, "home": home, "away": away})
                        
                        h2h_outcomes = {}
                        for bookmaker in match.get('bookmakers', []):
                            bk_name = bookmaker.get('title')
                            for market in bookmaker.get('markets', []):
                                if market.get('key') == 'h2h':
                                    for outcome in market.get('outcomes', []):
                                        name = outcome.get('name')
                                        price = outcome.get('price')
                                        
                                        if name not in h2h_outcomes:
                                            h2h_outcomes[name] = []
                                        h2h_outcomes[name].append({"price": price, "bookie": bk_name})
                        
                        if len(h2h_outcomes) >= 2:
                            avg_implied_probs = {}
                            best_prices = {}
                            
                            for name, odds_list in h2h_outcomes.items():
                                avg_odd = sum(o["price"] for o in odds_list) / len(odds_list)
                                avg_implied_probs[name] = 1.0 / avg_odd
                                best_prices[name] = max(odds_list, key=lambda x: x["price"])
                            
                            total_margin = sum(avg_implied_probs.values())
                            
                            for name, best_data in best_prices.items():
                                true_prob = (avg_implied_probs[name] / total_margin) * 100.0
                                best_odd = best_data["price"]
                                best_bookie = best_data["bookie"]
                                
                                ev_edge = (((true_prob / 100.0) * best_odd) - 1.0) * 100.0
                                label_name = "Match Draw" if name == "Draw" else f"{name} to Win"
                                
                                # Separate signals
                                prob_lock = "🔒 LOCK" if true_prob >= prob_threshold_t1 else "⚠️ LEAVE"
                                value_signal = "🔒 +EV VALUE" if ev_edge >= ev_threshold_t1 else "⚠️ NO VALUE"
                                
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
                                    "Value Signal": value_signal
                                })
                    
                    st.session_state["live_fixtures"] = extracted_fixtures
                    
                    df = pd.DataFrame(records)
                    if not df.empty:
                        # Sort by Value Signal first, then Prob Lock
                        df = df.sort_values(by=["Value Signal", "Prob Lock"], ascending=[True, True])
                        
                        lock_cnt = len(df[df["Prob Lock"] == "🔒 LOCK"])
                        val_cnt = len(df[df["Value Signal"] == "🔒 +EV VALUE"])
                        
                        m1, m2 = st.columns(2)
                        m1.metric("🔒 Probability Locks", lock_cnt)
                        m2.metric("🔒 +EV Value Opportunities", val_cnt)
                        
                        st.write(f"### 📋 Scanned Market Lines ({len(df)} Options)")
                        st.dataframe(df, use_container_width=True)
                    else:
                        st.warning("No open bookmaker odds returned for the selected leagues.")
                else:
                    st.info("Please select at least one league to scan.")
            else:
                st.warning("No active soccer leagues available right now.")
    else:
        st.info("Please enter your Odds API Key in the sidebar.")

# ==========================================
# TAB 2: TEAM & MATCH SPECIALS (+EV MATH)
# ==========================================
with tab2:
    st.subheader("Team Totals & BTTS Poisson Value Engine")
    st.markdown("Calculates true probabilities for **Team Over 1.5 Goals** and **BTTS** using $xG$ inputs. **Consumes 0 API credits.**")
    st.divider()

    col_t2_a, col_t2_b = st.columns(2)
    with col_t2_a:
        prob_threshold_t2 = st.slider("Probability 'Lock' Threshold (%)", 40, 80, 50, 5, key="prob_t2_slider")
    with col_t2_b:
        ev_threshold_t2 = st.slider("Minimum +EV Threshold (%)", 0.0, 10.0, 3.0, 0.5, key="ev_t2_slider")

    st.divider()
    live_list = st.session_state.get("live_fixtures", [])
    
    if live_list:
        st.success(f"🟢 **{len(live_list)} Real Fixtures Loaded from Tab 1 Scan**")
        fixture_options = [f["match"] for f in live_list]
        selected_match_name = st.selectbox("Select Real Match to Analyze:", fixture_options)
        
        selected_fixture = next(item for item in live_list if item["match"] == selected_match_name)
        home_team = selected_fixture["home"]
        away_team = selected_fixture["away"]
        
        st.markdown(f"#### Analyzing: **{home_team} vs {away_team}**")
        
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.caption(f"🏠 **{home_team} Metrics**")
            h_xg = st.number_input(f"{home_team} Expected Goals (xG)", 0.2, 4.0, 1.80, 0.05, key="h_xg")
            h_odds = st.number_input(f"Bookie Odds: {home_team} Over 1.5", 1.10, 10.0, 1.85, 0.05, key="h_odds")
            
        with col_m2:
            st.caption(f"✈️ **{away_team} Metrics**")
            a_xg = st.number_input(f"{away_team} Expected Goals (xG)", 0.2, 4.0, 1.20, 0.05, key="a_xg")
            a_odds = st.number_input(f"Bookie Odds: {away_team} Over 1.5", 1.10, 10.0, 2.40, 0.05, key="a_odds")
            
        btts_odds = st.number_input("Bookie Odds: BTTS Yes", 1.10, 10.0, 1.75, 0.05, key="btts_odds")
        
        # Poisson Math
        h_prob = (1.0 - math.exp(-h_xg) * (1.0 + h_xg)) * 100.0
        a_prob = (1.0 - math.exp(-a_xg) * (1.0 + a_xg)) * 100.0
        btts_prob = ((1.0 - math.exp(-h_xg)) * (1.0 - math.exp(-a_xg))) * 100.0
        
        h_ev = (((h_prob / 100.0) * h_odds) - 1.0) * 100.0
        a_ev = (((a_prob / 100.0) * a_odds) - 1.0) * 100.0
        btts_ev = (((btts_prob / 100.0) * btts_odds) - 1.0) * 100.0
        
        st.write("---")
        st.write("### 📊 Model Output & Dual Signals")
        
        results_df = pd.DataFrame([
            {
                "Selection": f"{home_team} Over 1.5 Goals",
                "Model Prob": f"{h_prob:.1f}%",
                "Prob Lock": "🔒 LOCK" if h_prob >= prob_threshold_t2 else "⚠️ LEAVE",
                "Fair Odds": f"{(100/h_prob):.2f}" if h_prob > 0 else "N/A",
                "Bookie Odds": f"{h_odds:.2f}",
                "EV Edge": f"{h_ev:+.1f}%",
                "Value Signal": "🔒 +EV VALUE" if h_ev >= ev_threshold_t2 else "⚠️ NO VALUE"
            },
            {
                "Selection": f"{away_team} Over 1.5 Goals",
                "Model Prob": f"{a_prob:.1f}%",
                "Prob Lock": "🔒 LOCK" if a_prob >= prob_threshold_t2 else "⚠️ LEAVE",
                "Fair Odds": f"{(100/a_prob):.2f}" if a_prob > 0 else "N/A",
                "Bookie Odds": f"{a_odds:.2f}",
                "EV Edge": f"{a_ev:+.1f}%",
                "Value Signal": "🔒 +EV VALUE" if a_ev >= ev_threshold_t2 else "⚠️ NO VALUE"
            },
            {
                "Selection": "Both Teams to Score (BTTS Yes)",
                "Model Prob": f"{btts_prob:.1f}%",
                "Prob Lock": "🔒 LOCK" if btts_prob >= prob_threshold_t2 else "⚠️ LEAVE",
                "Fair Odds": f"{(100/btts_prob):.2f}" if btts_prob > 0 else "N/A",
                "Bookie Odds": f"{btts_odds:.2f}",
                "EV Edge": f"{btts_ev:+.1f}%",
                "Value Signal": "🔒 +EV VALUE" if btts_ev >= ev_threshold_t2 else "⚠️ NO VALUE"
            }
        ])
        st.dataframe(results_df, use_container_width=True)

    else:
        st.info("👈 Run a live scan in **Tab 1 (Match Consensus Scanner)** first to automatically populate real upcoming matches here!")

# ==========================================
# TAB 3: xG PLAYER PROPS (+EV ENGINE)
# ==========================================
with tab3:
    st.subheader("Anytime Goalscorer Expected Value (+EV) Model")
    st.markdown("Combines **Understat $npxG_{90}$ metrics**, **fuzzy name matching**, and a **Poisson Distribution** to calculate true scoring probabilities.")
    
    col_t3_a, col_t3_b = st.columns(2)
    with col_t3_a:
        prob_threshold_t3 = st.slider("Probability 'Lock' Threshold (%)", 30, 70, 40, 5, key="prob_t3_slider")
    with col_t3_b:
        ev_threshold_t3 = st.slider("Minimum +EV Threshold (%)", 0.0, 10.0, 3.0, 0.5, key="ev_t3_slider")

    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        data_source = st.radio("Select Data Mode:", ["Demo Data (0 API Credits)", "Live API Data"], index=0, key="prop_mode")
    with col2:
        opp_factor = st.slider("Opponent Defense xGA Multiplier", 0.7, 1.5, 1.10, 0.05, key="opp_slider")
    
    exp_mins = st.slider("Expected Playing Minutes", 45, 90, 85, 5, key="mins_slider")

    if data_source == "Demo Data (0 API Credits)":
        understat_players = pd.DataFrame([
            {"player_name": "Erling Haaland", "team": "Manchester City", "npxg_per_90": 0.85},
            {"player_name": "Mohamed Salah", "team": "Liverpool", "npxg_per_90": 0.62},
            {"player_name": "Cole Palmer", "team": "Chelsea", "npxg_per_90": 0.54},
            {"player_name": "Alexander Isak", "team": "Newcastle", "npxg_per_90": 0.58},
            {"player_name": "Bukayo Saka", "team": "Arsenal", "npxg_per_90": 0.41},
        ])
        
        sample_props = [
            {"bookmaker": "Bet365", "raw_player_name": "E. Haaland", "odds": 1.75},
            {"bookmaker": "Unibet", "raw_player_name": "Mo Salah", "odds": 2.45},
            {"bookmaker": "Pinnacle", "raw_player_name": "Cole Palmer", "odds": 2.10},
            {"bookmaker": "Betway", "raw_player_name": "A. Isak", "odds": 2.85},
            {"bookmaker": "888sport", "raw_player_name": "B. Saka", "odds": 3.40},
        ]
        
        results = []
        understat_names = understat_players["player_name"].tolist()
        
        for item in sample_props:
            raw_name = item["raw_player_name"]
            odds = item["odds"]
            bookie = item["bookmaker"]
            
            best_match, match_score = process.extractOne(raw_name, understat_names, scorer=fuzz.token_set_ratio)
            
            if match_score >= 70:
                player_row = understat_players[understat_players["player_name"] == best_match].iloc[0]
                npxg_90 = player_row["npxg_per_90"]
                
                lambda_match = npxg_90 * opp_factor * (exp_mins / 90.0)
                model_prob = (1.0 - math.exp(-lambda_match)) * 100.0
                implied_prob = (1.0 / odds) * 100.0
                ev_percentage = (((model_prob / 100.0) * odds) - 1.0) * 100.0
                
                prob_lock = "🔒 LOCK" if model_prob >= prob_threshold_t3 else "⚠️ LEAVE"
                value_signal = "🔒 +EV VALUE" if ev_percentage >= ev_threshold_t3 else "⚠️ NO VALUE"
                
                results.append({
                    "Bookmaker": bookie,
                    "Bookie Name": raw_name,
                    "Matched Stats Player": best_match,
                    "Fuzz Match": f"{match_score}%",
                    "Odds": odds,
                    "Implied Prob": f"{implied_prob:.1f}%",
                    "Model Prob": f"{model_prob:.1f}%",
                    "Prob Lock": prob_lock,
                    "EV Edge": f"{ev_percentage:+.1f}%",
                    "Value Signal": value_signal
                })
        
        res_df = pd.DataFrame(results).sort_values(by="EV Edge", ascending=False)
        st.dataframe(res_df, use_container_width=True)
    else:
        st.warning("⚠️ Live API scanning for player props is on standby to protect your requests quota.")