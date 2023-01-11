import torch
import torch.nn as nn
from torch_geometric.nn import GCNConv, DeepGCNLayer, LayerNorm, Sequential
import torch.nn.functional as F
import pytorch_lightning as pl
from torch.optim import Adam
from GraphBuilder import GraphBuilder
from torchmetrics.functional import r2_score
from abc import ABC, abstractmethod


class MLP(pl.LightningModule):

    def __init__(self, input_size: int, hidden_sizes: list[int], output_size: int, dropout_prob: int = 0.3):
        super().__init__()
        print(f"MLP with: layers of size: {input_size} -> {hidden_sizes} -> {output_size}.")
        assert len(hidden_sizes) > 0, "MLP must have at least 1 hidden layer!"

        self.input_size = input_size
        self.hidden_size = hidden_sizes
        self.output_size = output_size

        self.input_layer = nn.Linear(input_size, hidden_sizes[0])
        self.layer_norm = nn.LayerNorm(hidden_sizes[0])
        self.dropout = nn.Dropout(dropout_prob)
        self.hidden = nn.Sequential()
        for i in range(len(hidden_sizes) - 1):
            self.hidden.append(nn.Linear(hidden_sizes[i], hidden_sizes[i + 1]))
            self.hidden.append(nn.LayerNorm(hidden_sizes[i + 1]))
            self.hidden.append(nn.ReLU())
            self.hidden.append(nn.Dropout(dropout_prob))

        self.output_layer = nn.Linear(hidden_sizes[-1], output_size)
        self.relu = nn.ReLU()

    def forward(self, x):
        x = self.relu(self.dropout(self.layer_norm(self.input_layer(x))))
        x = self.hidden(x)
        x = self.output_layer(x)
        return x

    def common_step(self, batch, split: str):
        x, y = batch
        out = self(x)
        loss = F.mse_loss(out, y)
        r2 = r2_score(out, y)
        self.log(f"{split} loss", loss, on_epoch=True, batch_size=len(x))
        self.log(f"{split} R2", r2, on_epoch=True, batch_size=len(x))
        return loss

    def training_step(self, batch, batch_idx):
        return self.common_step(batch, "training")

    def validation_step(self, batch, batch_idx):
        return self.common_step(batch, "validation")

    def test_step(self, batch, batch_idx):
        return self.common_step(batch, "test")

    def configure_optimizers(self):
        optimizer = Adam(self.parameters(), lr=1e-3)
        return optimizer


# for now using an MLP as encoder and decoder
class VariationalEncoder(nn.Module):

    def __init__(self, input_dim: int, hidden_dim: int, latent_dim: int):
        super().__init__()
        self.linear1 = nn.Linear(input_dim, hidden_dim)
        self.linear2 = nn.Linear(hidden_dim, hidden_dim)
        self.linear_mu = nn.Linear(hidden_dim, latent_dim)
        self.linear_sigma = nn.Linear(hidden_dim, latent_dim)

        self.N = torch.distributions.Normal(0, 1)
        # sample on the gpu
        self.N.loc = self.N.loc.cuda()
        self.N.scale = self.N.scale.cuda()
        self.kl = 0

    def forward(self, x):
        x = F.relu(self.linear1(x))
        x = F.relu(self.linear2(x))
        mu = self.linear_mu(x)
        sigma = torch.exp(self.linear_sigma(x))

        z = mu + sigma * self.N.sample(mu.shape)
        # print("mu:", mu)
        # print("sigma:", sigma)
        self.kl = (sigma**2 + mu**2 - torch.log(sigma) - 1 / 2).mean()
        return z

    def forward_det(self, x):
        """
        Returns the deterministic mean of the gaussian generated by the sample
        """
        x = F.relu(self.linear1(x))
        x = F.relu(self.linear2(x))
        mu = self.linear_mu(x)
        return mu


class Encoder(nn.Module):

    def __init__(self, input_dim: int, hidden_dim: int, latent_dim: int):
        super().__init__()
        self.linear1 = nn.Linear(input_dim, hidden_dim)
        self.linear2 = nn.Linear(hidden_dim, hidden_dim)
        self.linear3 = nn.Linear(hidden_dim, latent_dim)

    def forward(self, x):
        x = F.relu(self.linear1(x))
        x = F.relu(self.linear2(x))
        x = F.relu(self.linear3(x))
        return x


class Decoder(nn.Module):

    def __init__(self, latent_dim: int, hidden_dim: int, output_dim: int):
        super().__init__()
        self.linear1 = nn.Linear(latent_dim, hidden_dim)
        self.linear2 = nn.Linear(hidden_dim, hidden_dim)
        self.linear3 = nn.Linear(hidden_dim, output_dim)
        # self.regr = nn.Linear(output_dim, output_dim)

    def forward(self, x):
        x = F.relu(self.linear1(x))
        x = F.relu(self.linear2(x))
        return self.linear3(x)


class BaseAutoEncoder(ABC, pl.LightningModule):

    def __init__(self):
        super().__init__()
        self.edge_level = False

    def set_edge_level_graphbuilder(self, graph_builder: GraphBuilder):
        self.edge_level = True
        self.graph_builder = graph_builder

    def get_graph_batch(self, x):
        if self.edge_level:
            return self.graph_builder.compute_row_level_batch(x, self.device)
        else:
            return x

    @abstractmethod
    def get_latent(self, x):
        pass


class AutoEncoder(BaseAutoEncoder):

    def __init__(self, input_dim: int, latent_dim: int):
        super().__init__()
        self.save_hyperparameters()

        self.hidden_dim = (input_dim + latent_dim) // 2
        self.encoder = Encoder(input_dim, self.hidden_dim, latent_dim)
        self.decoder = Decoder(latent_dim, self.hidden_dim, input_dim)

    def forward(self, x):
        z = self.encoder(x)
        x_hat = self.decoder(z)
        return x_hat

    def get_latent(self, x):
        z = self.encoder(x)
        return z

    def common_step(self, batch):
        x, _ = batch
        x = self.get_graph_batch(x)
        x_hat = self(x)
        loss = F.mse_loss(x, x_hat)
        return loss

    def training_step(self, batch, batch_idx):
        loss = self.common_step(batch)
        self.log('training_loss', loss, on_epoch=True)
        return loss

    def validation_step(self, batch, batch_idx):
        loss = self.common_step(batch)
        self.log('validation_loss', loss, on_epoch=True)
        return loss

    def configure_optimizers(self):
        optimizer = Adam(self.parameters(), lr=1e-3)
        return optimizer


class VAE(BaseAutoEncoder):

    def __init__(self, input_dim: int, latent_dim: int):
        super().__init__()
        self.save_hyperparameters()

        self.hidden_dim = (input_dim + latent_dim) // 2
        self.encoder = VariationalEncoder(input_dim, self.hidden_dim, latent_dim)
        self.decoder = Decoder(latent_dim, self.hidden_dim, input_dim)

    def forward(self, x):
        z = self.encoder(x)
        x_hat = self.decoder(z)
        return x_hat

    def get_latent(self, x):
        z = self.encoder.forward_det(x)
        return z

    def common_step(self, batch):
        x, _ = batch
        x = self.get_graph_batch(x)
        x_hat = self(x)
        kl = self.encoder.kl
        loss = F.mse_loss(x, x_hat)
        return loss, kl

    def training_step(self, batch, batch_idx):
        loss, kl = self.common_step(batch)
        self.log('training_loss', loss, on_epoch=True)
        self.log('training_kl', kl, on_epoch=True)
        return loss + kl

    def validation_step(self, batch, batch_idx):
        loss, kl = self.common_step(batch)
        self.log('validation_loss', loss, on_epoch=True)
        self.log('validation_kl', kl, on_epoch=True)
        return loss + kl

    def configure_optimizers(self):
        optimizer = Adam(self.parameters(), lr=1e-3)
        return optimizer


class GNN(nn.Module):

    def __init__(self, in_channels: int, hidden_channels: int, out_channels: int, n_layers: int):
        super().__init__()
        self.n_layers = n_layers
        self.in_conv = GCNConv(in_channels, hidden_channels)
        self.in_norm = LayerNorm(hidden_channels)
        self.out_conv = GCNConv(hidden_channels, out_channels)
        self.out_norm = LayerNorm(out_channels)
        self.act = nn.ReLU()
        self.in_deeplayer = DeepGCNLayer(self.in_conv, self.in_norm, self.act)
        deeplayers_list = []
        for i in range(n_layers - 2):
            conv = GCNConv(hidden_channels, hidden_channels)
            norm = LayerNorm(hidden_channels)
            deeplayers_list.append((DeepGCNLayer(conv, norm, self.act), 'x, edge_index, edge_weight -> x'))
        self.hidden_deeplayers = Sequential('x, edge_index, edge_weight', deeplayers_list)
        self.out_deeplayer = DeepGCNLayer(self.out_conv, self.out_norm, self.act)

    def forward(self, node_matrix: torch.Tensor, edge_index: torch.Tensor, edge_weights) -> torch.Tensor:
        # x: Node feature matrix of shape [num_nodes, in_channels]
        # edge_index: Graph connectivity matrix of shape [2, num_edges]
        x = self.in_deeplayer(node_matrix, edge_index, edge_weights)
        x = self.hidden_deeplayers(x, edge_index, edge_weights)
        x = self.out_deeplayer(x.float(), edge_index, edge_weights)
        return x.float()


class UniversalGNN(pl.LightningModule):

    def __init__(self, latent_dim: int, hidden_dim: int, out_dim: int, n_layers: int, autoencoders_dict: dict[str, nn.Module],
                 graphbuilders_dict: dict[str, GraphBuilder], regressors_dict: dict[str, nn.Module]):
        super().__init__()
        self.save_hyperparameters()
        self.gnn = GNN(latent_dim, hidden_dim, out_dim, n_layers)
        self.autoencoders = nn.ModuleDict(autoencoders_dict)
        self.graphbuilders = graphbuilders_dict
        self.regressors = nn.ModuleDict(regressors_dict)
        if len(self.autoencoders) == 1:
            for dataset_name in self.autoencoders.keys():
                self.default_dataset_name = dataset_name

    def forward(self, x: torch.Tensor, dataset_name: str):
        batch_size = x.shape[0]
        nodes_matrix, edges_indeces, edges_weights = self.graphbuilders[dataset_name].compute_graph(x, self.device)
        out = self.gnn(nodes_matrix, edges_indeces, edges_weights)
        if self.graphbuilders[dataset_name].edge_level_batch:
            source = out[:batch_size]
            target = out[batch_size:]
            assert len(source) == len(target), f"""
                Error: edge-level batch has different sizes of source and target: {len(source)} vs {len(target)}"""
            out = torch.hstack([source, target])
        return self.regressors[dataset_name](out)

    def common_step(self, batch, split: str):
        if len(batch) == 3:
            x, y, dataset = batch
            dataset_name = type(dataset).__name__
        elif len(batch) == 2:
            x, y = batch
            dataset_name = self.default_dataset_name
        else:
            raise RuntimeError(f"Encountered abnormal batch of length {len(batch)}:\n {batch}")
        out = self(x, dataset_name)
        loss = F.mse_loss(out, y)
        r2 = r2_score(out, y)
        self.log(f"{dataset_name} {split} loss", loss, on_epoch=True, batch_size=len(x))
        self.log(f"{dataset_name} {split} R2", r2, on_epoch=True, batch_size=len(x))
        return loss

    def training_step(self, batch, batch_idx):
        return self.common_step(batch, "training")

    def validation_step(self, batch, batch_idx):
        return self.common_step(batch, "validation")

    def test_step(self, batch, batch_idx):
        return self.common_step(batch, "test")

    def configure_optimizers(self):
        optimizer = Adam(self.parameters(), lr=1e-3)
        return optimizer


if __name__ == "__main__":
    # GNN(5, 10, 3)
    from datasets import ClimARTDataset, MultiSplitDataset
    from torch.utils.data import DataLoader
    from pytorch_lightning.loggers import TensorBoardLogger

    dataset = MultiSplitDataset(ClimARTDataset)
    train_dataset, val_dataset, test_dataset = dataset.get_splits()
    print("train data mean:", train_dataset.data[0].mean())
    print("train data std:", train_dataset.data[0].std())
    print("val data mean:", val_dataset.data[0].mean())
    print("val data std:", val_dataset.data[0].std())
    train_loader = DataLoader(train_dataset, batch_size=128, num_workers=128, shuffle=True, drop_last=True)
    val_loader = DataLoader(val_dataset, batch_size=128, num_workers=128, shuffle=False, drop_last=True)
    vae = VAE(dataset.input_dim, 512)
    ae = AutoEncoder(dataset.input_dim, 512)

    ae_losses, vae_losses, kls = [], [], []
    ae_val_losses, vae_val_losses = [], []
    logger = TensorBoardLogger("./logs/", name="VAE", version="ClimART_train")
    vae_trainer = pl.Trainer(devices=1, accelerator="gpu", max_epochs=30, log_every_n_steps=10, logger=logger)
    vae_trainer.fit(vae, train_loader, val_loader)
    logger = TensorBoardLogger("./logs/", name="AE", version="ClimART_train")
    ae_trainer = pl.Trainer(devices=1, accelerator="gpu", max_epochs=30, log_every_n_steps=10, logger=logger)
    ae_trainer.fit(ae, train_loader, val_loader)

    import matplotlib.pyplot as plt
    vae_loss_line, ae_loss_line, vae_val_loss_line, ae_val_loss_line = plt.plot(vae_losses, "r", ae_losses, "b", vae_val_losses,
                                                                                "m", ae_val_losses, "c")
    vae_loss_line.set_label("VAE reconstruction loss")
    ae_loss_line.set_label("AE reconstruction loss")
    vae_val_loss_line.set_label("VAE val reconstruction loss")
    ae_val_loss_line.set_label("AE val reconstruction loss")
    plt.legend()
    plt.savefig("VAE_AE_losses_ClimART_train.png")
