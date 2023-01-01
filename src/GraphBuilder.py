import torch
import torch_geometric
import numpy as np
import scipy

class GraphBuilder:

    def __init__(self, distance_function, params_indeces, sparsity, encoder, edge_level_batch=False, device="cpu"):
        self.distance_function = distance_function
        self.params_indeces = params_indeces
        self.sparsity = sparsity
        self.encoder = encoder
        self.edge_level_batch = edge_level_batch
        self.device = device
    
    def compute_nodes_matrix(self, batch):
        return self.encoder(batch)

    def compute_edges_matrices(self, batch):
        params_indeces = torch.IntTensor(self.params_indeces)
        distance_features = torch.index_select(batch, dim=1, index=params_indeces)
        distance_features = distance_features.cpu().detach().numpy()
        distances_matrix = scipy.spatial.distance.cdist(distance_features, distance_features, self.distance_function)
        score_function = np.vectorize(self.score_function)
        scores_matrix = score_function(distances_matrix)
        sparsity_quantile = 1 - self.sparsity
        #quantile = np.quantile(scores_matrix, q=sparsity_quantile, axis=1)
        quantile = np.quantile(scores_matrix, q=sparsity_quantile)
        #quantiles_matrix = np.tile(quantiles.transpose(), reps=(1, 3))
        scores_matrix = np.where(scores_matrix > quantile, scores_matrix, 0)
        scores_matrix = scores_matrix/scores_matrix.max()
        scores_matrix = torch.from_numpy(scores_matrix).to(self.device)
        edges_indeces, edges_weights = torch_geometric.utils.dense_to_sparse(scores_matrix)
        return edges_indeces, edges_weights

    def score_function(self, x):
        if np.equal(x, 0) or np.equal(x, np.inf):
            result = 0
        else:
            result = 1/x
        return result

    def compute_row_level_batch(self, batch):
        raise NotImplementedError("Edge-level datasets have to be managed yet.")

    def compute_graph(self, batch):
        if self.edge_level_batch:
            batch = self.compute_row_level_batch(batch)
        nodes_matrix = self.compute_nodes_matrix(batch)
        edges_indeces, edges_weights = self.compute_edges_matrices(batch)
        return nodes_matrix, edges_indeces, edges_weights