# -*- coding: utf-8 -*-
"""
Created on Sun Dec  7 01:27:00 2025

@author: Max
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from scipy.linalg import eigh
import networkx as nx
import plotly.graph_objects as go
import plotly.io as pio
from sklearn.cluster import KMeans


data_path = '../data/processed/'
img_path = '../images/'

#Grabbing the CSVs from data_collection
df_champs = pd.read_csv(f'{data_path}final_champion_stats.csv')
df_synergy = pd.read_csv(f'{data_path}final_synergy_stats.csv')
df_counter = pd.read_csv(f'{data_path}final_counter_stats.csv')

#First, lets look at synergy
df_synergy = df_synergy.rename(columns={'WinRate': 'WinRate_A_x_B'})

#Filtering out duplicate pairs and pairs with less than 50 games
df_synergy = df_synergy[df_synergy['ChampionA'] != df_synergy['ChampionB']]
min_games = 50 
df_synergy = df_synergy[df_synergy['Games'] > min_games]

#Map individual win rates to the synergy pairs
df_synergy = df_synergy.merge(df_champs[['Unnamed: 0', 'WinRate']], left_on='ChampionA', right_on='Unnamed: 0').rename(columns={'WinRate': 'WinRate_A'}).drop(columns='Unnamed: 0')
df_synergy = df_synergy.merge(df_champs[['Unnamed: 0', 'WinRate']], left_on='ChampionB', right_on='Unnamed: 0').rename(columns={'WinRate': 'WinRate_B'}).drop(columns='Unnamed: 0')

#Calculate the lift
#Actual Pair WR - Average of Individual WRs
df_synergy['Expected_WR'] = (df_synergy['WinRate_A'] + df_synergy['WinRate_B']) / 2
df_synergy['Synergy_Score'] = df_synergy['WinRate_A_x_B'] - df_synergy['Expected_WR']

#PIVOT: Turn the list into a Matrix
#Index = Champ A, Columns = Champ B, Values = Synergy Score
adjacency_matrix = df_synergy.pivot(index='ChampionA', columns='ChampionB', values='Synergy_Score')

#Ensure the matrix is symmetric
adjacency_matrix = adjacency_matrix.combine_first(adjacency_matrix.T)

#Clean up the Matrix
#Fill NaNs with 0 (Champions that never played together have 0 synergy)
adjacency_matrix = adjacency_matrix.fillna(0)

#Fill Diagonal with 0 (A champion has no synergy with themselves for this math)
np.fill_diagonal(adjacency_matrix.values, 0)

#Computing the normalized laplacian with KNN clustering
k = 6
adj_knn = adjacency_matrix.copy()
for i in range(len(adj_knn)):
    row = adj_knn.iloc[i]
    #Find the threshold value for the Top k
    threshold = row.nlargest(k).min()
    #Set anything below that threshold to 0
    adj_knn.iloc[i] = row.where(row >= threshold, 0)

#Make it symmetric again
adj_knn = np.maximum(adj_knn.values, adj_knn.values.T)
adj_knn = pd.DataFrame(adj_knn, index=adjacency_matrix.index, columns=adjacency_matrix.columns)

#COMPUTE NORMALIZED LAPLACIAN
#L_synergy = I - D^-1/2 * A * D^-1/2
A = adj_knn.values
D = np.diag(np.sum(A, axis=1))

#Handle division by zero
with np.errstate(divide='ignore'):
    D_inv_sqrt = np.power(D, -0.5)
D_inv_sqrt[np.isinf(D_inv_sqrt)] = 0

#Compute Laplacian
L_synergy_knn = np.eye(len(A)) - D_inv_sqrt @ A @ D_inv_sqrt

#Eigendecomposition
eigenvalues, eigenvectors = eigh(L_synergy_knn)


#Create a DataFrame of the embedding
champions = adjacency_matrix.index.tolist()
x_axis = eigenvectors[:, 1]
y_axis = eigenvectors[:, 2]

df_embed = pd.DataFrame({
    'Champion': champions,
    'x (Fiedler)': x_axis,
    'y (Dim 3)': y_axis
})


#We use the first 5 eigenvectors for clustering (more dimensions = better separation)
embedding_dim = 5
X_spectral = eigenvectors[:, 1:embedding_dim+1] #Skip v0

#Force the model to find 6 clusters (Standard Role count)
kmeans = KMeans(n_clusters=8, random_state=5)
df_embed['Spectral_Cluster'] = kmeans.fit_predict(X_spectral)

#Plot the NEW "Math Roles"
plt.figure()
sns.scatterplot(
    data=df_embed, 
    x='x (Fiedler)', 
    y='y (Dim 3)', 
    hue='Spectral_Cluster', #Color by Math Cluster, not Riot Role
    palette='tab10', 
    s=100, alpha=0.9
)
plt.title("The 'True' Classes of League (Spectral Clustering n=8)")
plt.savefig(f'{img_path}fiedler_spectrum.png')
plt.show()

#Print who is in each cluster to analyze them
for i in range(8):
    print(f"\n--- Cluster {i} ---")
    print(df_embed[df_embed['Spectral_Cluster'] == i]['Champion'].tolist())


#Generating 3D Network Topology
G = nx.from_numpy_array(adj_knn.to_numpy())

pos = nx.spring_layout(G, dim=3, seed=5, weight='weight', iterations=100)
x_nodes = [pos[i][0] for i in G.nodes()]
y_nodes = [pos[i][1] for i in G.nodes()]
z_nodes = [pos[i][2] for i in G.nodes()]

edge_threshold = 0.02
x_edges = []
y_edges = []
z_edges = []

for u, v, d in G.edges(data=True):
    if d['weight'] > edge_threshold:
        x_edges += [pos[u][0], pos[v][0], None] #None breaks the line segment
        y_edges += [pos[u][1], pos[v][1], None]
        z_edges += [pos[u][2], pos[v][2], None]
        
fig = go.Figure()
fig.add_trace(go.Scatter3d(
    x=x_nodes, y=y_nodes, z=z_nodes,
    mode='markers',
    marker=dict(
        size=6,
        opacity=0.9,
        color=df_embed['Spectral_Cluster']
    ),
    hoverinfo='text',
    text=champions,
))

fig.add_trace(go.Scatter3d(
        x=x_edges, y=y_edges, z=z_edges,
        mode='lines',
        opacity=0.25,
        line=dict(color='grey', width=1),
        hoverinfo='none'
    ))

fig.update_layout(
    title="3D Network Topology of the Meta (Rotatable)",
    width=900, height=700,
    showlegend=False,
    scene=dict(
        xaxis=dict(showticklabels=False, title=''),
        yaxis=dict(showticklabels=False, title=''),
        zaxis=dict(showticklabels=False, title='')
    )
)
fig.write_html(f'{img_path}3d_topology.html')
pio.renderers.default = "browser"
fig.show()


#Lets now work with counters to try and find some cool things about the meta
#Mapping counters to clusters
#Create the Mirror (B vs A)
df_inverse = df_counter.copy()

#Swap the champions
df_inverse['ChampionA'] = df_counter['ChampionB']
df_inverse['ChampionB'] = df_counter['ChampionA']

#Invert the result (If A won 6/10, then B won 4/10)
df_inverse['Wins'] = df_counter['Games'] - df_counter['Wins']
df_inverse['WinRate'] = df_inverse['Wins'] / df_inverse['Games']

#Combine Original + Mirror
df_counter_full = pd.concat([df_counter, df_inverse], ignore_index=True)


cluster_map = df_embed.set_index('Champion')['Spectral_Cluster'].to_dict()
df_counter_full['ClusterA'] = df_counter_full['ChampionA'].map(cluster_map)
df_counter_full['ClusterB'] = df_counter_full['ChampionB'].map(cluster_map)

#Filtering valid pairs (drop where champs are in the same cluster)
df_valid = df_counter_full[df_counter_full['ClusterA'] != df_counter_full['ClusterB']]

#Aggregate Wins/Games by Cluster Pair
cluster_stats = df_valid.groupby(['ClusterA', 'ClusterB'])[['Wins', 'Games']].sum().reset_index()
cluster_stats['WinRate'] = cluster_stats['Wins'] / cluster_stats['Games']

matrix_cluster = cluster_stats.pivot(index='ClusterA', columns='ClusterB', values='WinRate')

plt.figure()
sns.heatmap(matrix_cluster, annot=True, fmt=".1%", cmap="RdBu_r", center=0.5)
plt.title("Archetype Warfare: Which Style Beats Which?")
plt.xlabel("Opponent Cluster")
plt.ylabel("My Cluster")
plt.savefig(f'{img_path}cluster_vs_cluster.png')
plt.show()


#Using the Fiedler Vector to Analyze the Primary Division of the meta
df_fiedler = pd.DataFrame({
    'Champion': adjacency_matrix.index,
    'Fiedler_Score': eigenvectors[:, 1]
})

#Sort and Filter
df_fiedler = df_fiedler.sort_values('Fiedler_Score')
top_20 = df_fiedler.tail(20)
bottom_20 = df_fiedler.head(20)
df_plot = pd.concat([bottom_20, top_20])

#Plot
plt.figure(figsize=(12,10))
#Color bars: Red for negative, Blue for positive
colors = ['red' if x < 0 else 'blue' for x in df_plot['Fiedler_Score']]

plt.barh(df_plot['Champion'], df_plot['Fiedler_Score'], color=colors)
plt.title("The Spectrum of the Primary Division of the Meta (Fiedler Vector)")
plt.xlabel("Polarity Score (Dimension 1)")
plt.grid(axis='x', alpha=0.3)
plt.axvline(0, color='black', linewidth=0.8)

plt.tight_layout()
plt.savefig(f'{img_path}fiedler_vector.png')
plt.show()



#Eigenvector Centrality
#Compute Eigenvectors of adjacency matrix (A)
evals_A, evecs_A = eigh(adjacency_matrix.values)

#The dominant eigenvector of the adjacency matrix is the last one
centrality_vector = evecs_A[:, -1]

#Create DataFrame
#Need "Games" (Popularity) to compare against Centrality
df_centrality = pd.DataFrame({
    'Champion': adjacency_matrix.index,
    'Centrality': np.abs(centrality_vector), #Absolute value to be safe
    'Games': df_champs.set_index('Unnamed: 0').loc[adjacency_matrix.index]['Games']
})

#Plot (Popularity vs. Influence)
plt.figure(figsize=(14, 10))
sns.scatterplot(data=df_centrality, x='Games', y='Centrality', s=100, alpha=0.7, color='purple')

#Label the "Keystones" (High Centrality) and "Popular Fillers" (High Games, Low Centrality)
#Label the top 15 most central champs
top_central = df_centrality.nlargest(15, 'Centrality')

for _, row in top_central.iterrows():
    plt.text(row['Games']+50, row['Centrality'], row['Champion'], fontsize=10, weight='bold')

plt.title("The 'Keystones' of the Meta: Popularity vs. Network Influence", fontsize=16)
plt.xlabel("Pick Volume (Total Games)", fontsize=12)
plt.ylabel("Eigenvector Centrality (Network Influence)", fontsize=12)
plt.grid(True, alpha=0.3)
plt.savefig(f'{img_path}eigenvector_centrality.png')
plt.show()



#Versatility Chart
x = eigenvectors[:, 1]
y = eigenvectors[:, 2]
distances = np.sqrt(x**2 + y**2)

df_versatility = pd.DataFrame({
    'Champion': adjacency_matrix.index,
    'Distance': distances
})

#Sort
df_versatility = df_versatility.sort_values('Distance')

#Plot Versatility
specialists = df_versatility.tail(20)
generalists = df_versatility.head(20)

plt.figure(figsize=(12,18))
plt.barh(df_versatility['Champion'], df_versatility['Distance'])
plt.title("Versatility Chart")
plt.ylabel("Champions")
plt.xlabel("Spectral Distance from Origin")
plt.gca().invert_yaxis()
plt.yticks(fontsize=6)
plt.savefig(f'{img_path}total_versatility_chart.png')
plt.show()

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))

#Generalists (Low Distance)
ax1.barh(generalists['Champion'], generalists['Distance'], color='gray')
ax1.set_title("The Generalists (Closest to Origin)")
ax1.set_xlabel("Spectral Distance")
ax1.invert_yaxis()

#Specialists (High Distance)
ax2.barh(specialists['Champion'], specialists['Distance'], color='orange')
ax2.set_title("The Specialists (Furthest from Origin)")
ax2.set_xlabel("Spectral Distance")
ax2.invert_yaxis()

plt.tight_layout()
plt.savefig(f'{img_path}versatility_chart.png')
plt.show()