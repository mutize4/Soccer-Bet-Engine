# --- HELPER FUNCTION UPDATE ---
@st.cache_data(ttl=1800)
def fetch_soccer_odds(key, sports_tuple):
    all_fixtures = []
    # Added 'btts' to requested markets
    markets = "h2h,totals,btts"
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


# ==========================================
# TAB 1: MATCH CONSENSUS SCANNER (H2H, Totals, BTTS)
# ==========================================
with tab1:
    st.subheader("Match Winner, Totals & BTTS Scanner")
    st.markdown("Scans consensus market lines (**H2H**, **Over/Under 2.5**, and **BTTS**), de-vigs house margin, and checks **Prob Lock** and **+EV Edge**.")
    
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
                        totals_outcomes = {}
                        btts_outcomes = {}
                        
                        for bookmaker in match.get('bookmakers', []):
                            bk_name = bookmaker.get('title')
                            for market in bookmaker.get('markets', []):
                                key = market.get('key')
                                
                                # 1. Match Winner (H2H)
                                if key == 'h2h':
                                    for outcome in market.get('outcomes', []):
                                        name = outcome.get('name')
                                        price = outcome.get('price')
                                        if name not in h2h_outcomes:
                                            h2h_outcomes[name] = []
                                        h2h_outcomes[name].append({"price": price, "bookie": bk_name})
                                
                                # 2. Over/Under 2.5 Goals
                                elif key == 'totals':
                                    for outcome in market.get('outcomes', []):
                                        if outcome.get('point') == 2.5:
                                            name = f"{outcome.get('name')} 2.5 Goals"
                                            price = outcome.get('price')
                                            if name not in totals_outcomes:
                                                totals_outcomes[name] = []
                                            totals_outcomes[name].append({"price": price, "bookie": bk_name})
                                
                                # 3. Both Teams To Score (BTTS)
                                elif key == 'btts':
                                    for outcome in market.get('outcomes', []):
                                        name = f"BTTS {outcome.get('name')}"
                                        price = outcome.get('price')
                                        if name not in btts_outcomes:
                                            btts_outcomes[name] = []
                                        btts_outcomes[name].append({"price": price, "bookie": bk_name})
                        
                        # Helper evaluator
                        def process_market_dict(market_dict):
                            if len(market_dict) >= 2:
                                avg_implied_probs = {}
                                best_prices = {}
                                
                                for name, odds_list in market_dict.items():
                                    avg_odd = sum(o["price"] for o in odds_list) / len(odds_list)
                                    avg_implied_probs[name] = 1.0 / avg_odd
                                    best_prices[name] = max(odds_list, key=lambda x: x["price"])
                                
                                total_margin = sum(avg_implied_probs.values())
                                
                                for name, best_data in best_prices.items():
                                    true_prob = (avg_implied_probs[name] / total_margin) * 100.0
                                    best_odd = best_data["price"]
                                    best_bookie = best_data["bookie"]
                                    
                                    ev_edge = (((true_prob / 100.0) * best_odd) - 1.0) * 100.0
                                    
                                    # Format label cleanly
                                    if name == "Draw":
                                        label_name = "Match Draw"
                                    elif "2.5 Goals" not in name and "BTTS" not in name:
                                        label_name = f"{name} to Win"
                                    else:
                                        label_name = name
                                    
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

                        process_market_dict(h2h_outcomes)
                        process_market_dict(totals_outcomes)
                        process_market_dict(btts_outcomes)
                    
                    st.session_state["live_fixtures"] = extracted_fixtures
                    
                    df = pd.DataFrame(records)
                    if not df.empty:
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
