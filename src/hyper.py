import os
from datasets import ClimARTDataset, UberMovementDataset, BuildingElectricityDataset

class HyperParameter:

    """
    Bundles a bunch of hyper parameters.
    """
    
    # choose which results to save
    SAVE_BASELINE_RESULTS = True
    
    # Choose which experiments to run
    RUN_MAIN_EXPERIMENTS = True
    RUN_BASELINE_EXPERIMENTS = False
    
    # Choose which baseline experiments to run
    RUN_BASELINE_RF = True
    RUN_BASELINE_GB = True
    RUN_BASELINE_MLP = True
    
    # Choose which dataset to consider
    UBERMOVEMENT = True
    CLIMART = True
    BUILDINGELECTRICITY = True
    
    # model parameters
    LATENT_DIM = 512
    
    # trainng parameters
    MAX_EPOCHS = 30
    BATCH_SIZE_BASELINE = 2048
    EPOCHS_BASELINE = 20
    
    # random seed
    SEED = 3
    
    # data paths
    PATH_TO_RESULTS = 'results/'
    
        
    def __init__(self):
    
        """ """
        
        # add datasets we cant to consider to list
        self.DATASET_CLASS_LIST = []
        if self.UBERMOVEMENT:
            self.DATASET_CLASS_LIST.append(UberMovementDataset)
        if self.CLIMART:
            self.DATASET_CLASS_LIST.append(ClimARTDataset)
        if self.BUILDINGELECTRICITY:
            self.DATASET_CLASS_LIST.append(BuildingElectricityDataset)
            
        # create result directories here
        self.check_create_dir(self.PATH_TO_RESULTS)
        
        
    def check_create_dir(self, path):
    
        """ """
        
        if not os.path.isdir(path):
            os.mkdir(path)
