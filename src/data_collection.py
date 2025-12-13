# -*- coding: utf-8 -*-
"""
Created on Sun Dec  7 01:04:47 2025

@author: Max
"""

from riotwatcher import LolWatcher, ApiError
import pandas as pd
import itertools
from collections import defaultdict
import random
import pickle

def read_pickle(path_in, name_in):
    the_data_t = pickle.load(
        open(path_in + name_in + ".pk", "rb"))
    return the_data_t

def write_pickle(obj_in, path_in, name_in):
    pickle.dump(obj_in, open(
        path_in + name_in + ".pk", "wb"))

output_path = '../data/raw/'


#Configuration
api_key = 'YOUR_API_KEY_HERE'
watcher = LolWatcher(api_key)
region = 'na1'
total_seeds = 10_000

#Defining ranked distribution
#Rank % determines the weight for that specific Division.
DISTRIBUTION = {
    'IRON':     {'I': 2.7, 'II': 3.4, 'III': 3.6, 'IV': 3.9},
    'BRONZE':   {'I': 3.4, 'II': 4.2, 'III': 4.2, 'IV': 5.0},
    'SILVER':   {'I': 3.7, 'II': 5.1, 'III': 5.5, 'IV': 7.0},
    'GOLD':     {'I': 2.7, 'II': 4.3, 'III': 5.4, 'IV': 9.0},
    'PLATINUM': {'I': 1.7, 'II': 2.6, 'III': 3.4, 'IV': 6.3},
    'EMERALD':  {'I': 2.1, 'II': 1.4, 'III': 2.0, 'IV': 4.2},
    'DIAMOND':  {'I': 0.37, 'II': 0.77, 'III': 0.35, 'IV': 0.93}
}

#Apex tiers don't have divisions
APEX_DISTRIBUTION = {
    'MASTER': 0.41,
    'GRANDMASTER': 0.043,
    'CHALLENGER': 0.02
}

seed_summoners = []

print(f"Calculated Sample Targets for N={total_seeds}...")

#Harvest standard tiers (IRON -> DIAMOND)
for tier, divisions in DISTRIBUTION.items():
    for division, percentage in divisions.items():
        #Calculate exactly how many players to grab to match the population
        target_count = int(total_seeds * (percentage / 100))
        current_collected = 0
        current_page = 1
        
        print(f"Collecting {target_count} seeds from {tier} {division}...")
            
        while current_collected < target_count:
            try:
                #Fetch the current page
                entries = watcher.league.entries(region, 'RANKED_SOLO_5x5', tier, division, page=current_page)
                
                #Stop if Riot returns an empty list (end of the ladder)
                if not entries:
                    print(f"Ran out of players in {tier} {division} at page {current_page}!")
                    break
                
                #Shuffle to avoid alphabetical bias
                random.shuffle(entries)
                
                #Calculate how many are needed
                needed = target_count - current_collected
                
                #Take either the whole page, or just enough to finish the job
                batch = entries[:needed]
                
                for entry in batch:
                    seed_summoners.append(entry['puuid'])
                
                current_collected += len(batch)
                current_page += 1
                
            except ApiError as e:
                print(f"Error fetching {tier} {division} page {current_page}: {e}")
                break

#Harvest Apex Tiers (MASTER+)
for tier, percentage in APEX_DISTRIBUTION.items():
    target_count = int(total_seeds * (percentage / 100))
    
    if target_count < 1:
        print(f"Skipping {tier} (Math requires {target_count} players)")
        continue
        
    try:
        if tier == 'CHALLENGER':
            league = watcher.league.challenger_by_queue(region, 'RANKED_SOLO_5x5')
        elif tier == 'GRANDMASTER':
            league = watcher.league.grandmaster_by_queue(region, 'RANKED_SOLO_5x5')
        else: #Master
            league = watcher.league.masters_by_queue(region, 'RANKED_SOLO_5x5')
            
        batch = random.sample(league['entries'], min(target_count, len(league['entries'])))
        print(f"Collecting {target_count} seeds from {tier}...")
        
        for entry in batch:
            seed_summoners.append(entry['puuid'])
            
    except ApiError as e:
        print(f"Error fetching {tier}: {e}")

print("Harvest Complete")
print(f"Total Unique Seeds: {len(seed_summoners)}")

final_seed_summoners = seed_summoners.copy()
write_pickle(final_seed_summoners, output_path, 'seed_summoners')

#Harvest Match IDs (Iterate through seed players to find unique matches)
match_ids = set()
seed_summoners = read_pickle(output_path, 'seed_summoners')
print(f"Harvesting matches from {len(seed_summoners)} players...")

for i, puuid in enumerate(seed_summoners):
    try:
        #Directly call matchlist using the puuid
        matches = watcher.match.matchlist_by_puuid(region, puuid, count=20)
        match_ids.update(matches)
        
        #Simple progress logger
        if i % 100 == 0:
            print(f"Processed {i}/{len(seed_summoners)} players... (Unique Matches: {len(match_ids)})")
            
    except ApiError as err:
        if err.response.status_code == 404:
            continue #Player has no matches
        else:
            print(f"Error: {err}")

print(f"FINAL COUNT: {len(match_ids)} Unique Match IDs collected.")

final_match_ids = match_ids.copy()
write_pickle(final_match_ids, output_path, 'match_ids')

match_ids = read_pickle(output_path, 'match_ids')

#Collect game info
champion_wins = defaultdict(int)
champion_games = defaultdict(int)
pair_wins = defaultdict(int)
pair_games = defaultdict(int)
matchup_games = defaultdict(int)
matchup_wins = defaultdict(int)


processed_count = 0

#This section will take several days due to API key rate limits
print(f"Processing {len(match_ids)} matches...")

for match_id in list(match_ids):
    match_detail = watcher.match.by_id(region, match_id)
    
    #Extract teams
    blue_team = []
    red_team = []
    blue_win = False
    
    for p in match_detail['info']['participants']:
        c_name = p['championName']
        champion_games[c_name] += 1
        if p['win']:
            champion_wins[c_name] += 1
        
        if p['teamId'] == 100:
            blue_team.append(c_name)
            if p['win']: blue_win = True
        else:
            red_team.append(c_name)

#Process pairs (synergy)
    for team, won in [(blue_team, blue_win), (red_team, not blue_win)]:
            #Create all unique pairs of 2 champions from the team of 5
            for c1, c2 in itertools.combinations(sorted(team), 2):
                pair_key = (c1, c2)
                pair_games[pair_key] += 1
                if won:
                    pair_wins[pair_key] += 1
#Process pairs (counters)
    for b_champ in blue_team:
        for r_champ in red_team:
            
            #Sorting the pair so (Yasuo, Yone) is treated the same as (Yone, Yasuo). The first element is the 'Reference'
            if b_champ < r_champ:
                key = (b_champ, r_champ)
                c1_is_blue = True  #The 'Reference' champion is on Blue team
            else:
                key = (r_champ, b_champ)
                c1_is_blue = False #The 'Reference' champion is on Red team
            
            matchup_games[key] += 1
            #Tracking the win
            #Only track wins for the reference
            #If Blue Won and c1 was Blue -> c1 won.
            #If Red Won and c1 was Red -> c1 won.
            if (blue_win and c1_is_blue) or (not blue_win and not c1_is_blue):
                matchup_wins[key] += 1
    processed_count += 1
    if processed_count == 1:
        print(f"{processed_count}/{len(match_ids)} matches processed")
    elif processed_count % 1000 == 0:
        print(f"{processed_count}/{len(match_ids)} matches processed")
        write_pickle(champion_wins, output_path, 'champion_wins')
        write_pickle(champion_games, output_path, 'champion_games')
        write_pickle(pair_wins, output_path, 'pair_wins')
        write_pickle(pair_games, output_path, 'pair_games')
        write_pickle(matchup_games, output_path, 'matchup_games')
        write_pickle(matchup_wins, output_path, 'matchup_wins')


write_pickle(champion_wins, output_path, 'champion_wins')
write_pickle(champion_games, output_path, 'champion_games')
write_pickle(pair_wins, output_path, 'pair_wins')
write_pickle(pair_games, output_path, 'pair_games')
write_pickle(matchup_games, output_path, 'matchup_games')
write_pickle(matchup_wins, output_path, 'matchup_wins')

champion_wins = read_pickle(output_path, 'champion_wins')
champion_games = read_pickle(output_path, 'champion_games')
pair_wins = read_pickle(output_path, 'pair_wins')
pair_games = read_pickle(output_path, 'pair_games')
matchup_games = read_pickle(output_path, 'matchup_games')
matchup_wins = read_pickle(output_path, 'matchup_wins')

#Final export
#Construct the Final DataFrames for Analysis
#Champion Stats
df_champs = pd.DataFrame(index=champion_games.keys())
df_champs['Games'] = df_champs.index.map(champion_games)
df_champs['Wins'] = df_champs.index.map(champion_wins)
df_champs['WinRate'] = df_champs['Wins'] / df_champs['Games']
df_champs.to_csv('../data/processed/final_champion_stats.csv')

#Synergy Stats
synergy_rows = []
for (c1, c2), games in pair_games.items():
    wins = pair_wins.get((c1, c2), 0)
    synergy_rows.append({
        'ChampionA': c1,
        'ChampionB': c2,
        'Games': games,
        'Wins': wins,
        'WinRate': wins / games
    })
pd.DataFrame(synergy_rows).to_csv('../data/processed/final_synergy_stats.csv', index=False)

#Counter Stats
counter_rows = []
for (c1, c2), games in matchup_games.items():
    wins = matchup_wins.get((c1, c2), 0)
    counter_rows.append({
        'ChampionA': c1,
        'ChampionB': c2,
        'Games': games,
        'Wins': wins, #Wins for ChampionA
        'WinRate': wins / games #WinRate for ChampionA vs ChampionB
    })
pd.DataFrame(counter_rows).to_csv('../data/processed/final_counter_stats.csv', index=False)