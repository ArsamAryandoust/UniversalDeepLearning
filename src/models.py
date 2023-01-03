import torch
import torch.nn as nn
from torch_geometric.nn import GCNConv
import torch.nn.functional as F
import pytorch_lightning as pl
from torch.optim import Adam
from datasets import CheckedDataset
from sklearn.metrics import r2_score

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

        z = mu + sigma*self.N.sample(mu.shape)
        # print("mu:", mu)
        # print("sigma:", sigma)
        self.kl = (sigma**2 + mu**2 - torch.log(sigma) - 1/2).mean()
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
    def __init__(self, latent_dim:int, hidden_dim: int, output_dim:int):
        super().__init__()
        self.linear1 = nn.Linear(latent_dim, hidden_dim)
        self.linear2 = nn.Linear(hidden_dim, hidden_dim)
        self.linear3 = nn.Linear(hidden_dim, output_dim)
        # self.regr = nn.Linear(output_dim, output_dim)
    
    def forward(self, x):
        x = F.relu(self.linear1(x))
        x = F.relu(self.linear2(x))
        return self.linear3(x)

class AutoEncoder(pl.LightningModule):
    def __init__(self, input_dim: int, latent_dim: int):
        super().__init__()
        self.save_hyperparameters()

        self.hidden_dim = (input_dim + latent_dim)//2
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
        x, _ =  batch
        x_hat = self(x)
        loss = F.mse_loss(x, x_hat)
        return loss
    
    def training_step(self, batch, batch_idx):
        loss = self.common_step(batch)
        self.log('training_loss', loss, on_epoch=True)
        ae_losses.append(float(loss))
        return loss

    def validation_step(self, batch, batch_idx):
        loss = self.common_step(batch)
        self.log('validation_loss', loss, on_epoch=True)
        ae_val_losses.append(float(loss))
        return loss

    def configure_optimizers(self):
        optimizer = Adam(self.parameters(), lr=1e-3)
        return optimizer

class VAE(pl.LightningModule):
    def __init__(self, input_dim: int, latent_dim: int):
        super().__init__()
        self.save_hyperparameters()

        self.hidden_dim = (input_dim + latent_dim)//2
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
        x, _ =  batch
        x_hat = self(x)
        kl = self.encoder.kl
        loss = F.mse_loss(x, x_hat)

        # print("kl:", kl)
        # print("loss:",loss)
        return loss, kl
    
    def training_step(self, batch, batch_idx):
        loss, kl = self.common_step(batch)
        self.log('training_loss', loss, on_epoch=True)
        self.log('training_kl', kl, on_epoch=True)
        vae_losses.append(float(loss))
        kls.append(float(kl))
        return loss + kl

    def validation_step(self, batch, batch_idx):
        loss, kl = self.common_step(batch)
        self.log('validation_loss', loss, on_epoch=True)
        self.log('validation_kl', kl, on_epoch=True)
        vae_val_losses.append(float(loss))
        return loss + kl

    def configure_optimizers(self):
        optimizer = Adam(self.parameters(), lr=1e-3)
        return optimizer

class GNN(nn.Module):
    def __init__(self, in_channels: int, hidden_channels: int, out_channels: int):
        super().__init__()
        self.save_hyperparameters()
        self.conv1 = GCNConv(in_channels, hidden_channels)
        self.conv2 = GCNConv(hidden_channels, out_channels)

    def forward(self, node_matrix: torch.Tensor, edge_index: torch.Tensor, edge_weights) -> torch.Tensor:
        # x: Node feature matrix of shape [num_nodes, in_channels]
        # edge_index: Graph connectivity matrix of shape [2, num_edges]
        x = self.conv1(x, edge_index, edge_weights).relu()
        x = self.conv2(x, edge_index, edge_weights)
        return x

class UniversalGNN(pl.LightningModule):
    def __init__(self, latent_dim):
        super().__init__()
        self.gnn = GNN(latent_dim, ..., ...)
    
    def forward(self, x: torch.Tensor, dataset: CheckedDataset):
        nodes_matrix, edges_indeces, edges_weights = dataset.graph_builder.compute_graph(x)
        out = self.gnn(nodes_matrix, edges_indeces, edges_weights)
        return dataset.regressor(out)

    def common_step(self, batch, split:str):
        x, y, dataset = batch
        out = self(x, dataset)
        loss = F.mse_loss(out, y)
        r2 = r2_score(y, out)
        self.log(f"{split} loss", loss, on_epoch=True)
        self.log(f"{split} R2", r2, on_epoch=True)
        return loss

    def training_step(self, batch, batch_idx):
        return self.common_step(batch, "training")
    
    def validation_step(self, batch, batch_idx):
        return self.common_step(batch, "validation")
    
    def validation_step(self, batch, batch_idx):
        return self.common_step(batch, "test")
        

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
    ae_val_losses, vae_val_losses= [], []
    logger = TensorBoardLogger("./logs/", name="VAE", version="ClimART_train")
    vae_trainer = pl.Trainer(devices=1, accelerator="gpu", max_epochs=30, log_every_n_steps=10, logger=logger)
    vae_trainer.fit(vae, train_loader, val_loader)
    logger = TensorBoardLogger("./logs/", name="AE", version="ClimART_train")
    ae_trainer = pl.Trainer(devices=1, accelerator="gpu", max_epochs=30, log_every_n_steps=10, logger=logger)
    ae_trainer.fit(ae, train_loader, val_loader)

    import matplotlib.pyplot as plt
    vae_loss_line, ae_loss_line, vae_val_loss_line, ae_val_loss_line = plt.plot(vae_losses, "r", ae_losses, "b", vae_val_losses, "m", ae_val_losses, "c")
    vae_loss_line.set_label("VAE reconstruction loss")
    ae_loss_line.set_label("AE reconstruction loss")
    vae_val_loss_line.set_label("VAE val reconstruction loss")
    ae_val_loss_line.set_label("AE val reconstruction loss")
    plt.legend()
    plt.savefig("VAE_AE_losses_ClimART_train.png")

    

    