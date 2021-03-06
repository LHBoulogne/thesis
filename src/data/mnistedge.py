import torch
import cv2
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, datasets
import os   

import pickle

import numpy as np
from PIL import Image

class MNIST_edge(Dataset) :
    def __init__(self, config, transform=None, root='../../../data/mnist') :
        if not len(set(config.labels1)) == len(config.labels1):
            raise RuntimeError("config.labels1 must not contain duplicates")
        if not len(set(config.labels2)) == len(config.labels2):
            raise RuntimeError("config.labels2 must not contain duplicates")

        self.dataset = datasets.MNIST(root=root, download=True)
        self.transform = transform
        label_file_name = os.path.join(root, 'labels.pkl')
        
        if os.path.exists(label_file_name):
            with open(label_file_name, "rb" ) as f:
                self.label_dict = pickle.load(f)
        else:
            self.create_label_dict(label_file_name)

        if config.balance and not config.labels1 == config.labels2:
            (self.original_probs, self.edge_probs) = self.get_balanced_probs(config.labels1, config.labels2)
        else:
            self.original_probs = self.uniform_label_dict(config.labels1)
            self.edge_probs = self.uniform_label_dict(config.labels2)

        self.length = config.batches * config.mini_batch_size
            
    def get_balanced_probs(self, labels1, labels2):
        if len(labels2) < len(labels1):
            return self.get_balanced_probs(labels2, labels1)
        if not len(labels1) + 1 == len(labels2):
            raise NotImplementedError("Balancing for multiple missing labels is not implemented yet.")

        probs1 = self.uniform_label_dict(labels1)
        q = len(labels1) # is the same as len(labels2)-1
        p = (q-1)/(q*(q+1))
        probs2 = {}
        for label in labels2:
            probs2[label] = p
            if not label in labels1:
                probs2[label] += 1/q

        return (probs1, probs2)

    def uniform_label_dict(self, labels):
        probs = {}
        p = 1.0/len(labels)
        for label in labels:
            probs[label] = p
        return probs

    def create_label_dict(self, filename) :
        print("Creating label dictionary...")
        self.label_dict = {}
        for it in range(10):
            self.label_dict[it] = []
        print("\r" + str(0) + '/' + str(self.dataset.__len__()), end='\r')
        for idx in range(self.dataset.__len__()):
            _, label = self.dataset.__getitem__(idx)
            print("\r" + str(idx+1) + '/' + str(self.dataset.__len__()), end='\r')
            self.label_dict[label] += [idx]
            
        with open(filename, "wb" ) as f:
            pickle.dump(self.label_dict, f)
        print("Label dictionary saved.")

    #large number that should not be reached
    def __len__(self):
        return self.length

    #probs should add up to 1
    def random_label(self, probs):
        r = np.random.rand()
        probsum = 0
        keys = list(probs.keys())
        for key in keys:
            label = key
            probsum += probs[key]
            if probsum >= r:
                break
        return label


    #idx is not used. Random combinations of data points are returned 
    def __getitem__(self, idx):
        np.random.seed()
        original_class = self.random_label(self.original_probs)
        edge_class     = self.random_label(self.edge_probs)

        original_idcs = self.label_dict[original_class]
        edge_idcs = self.label_dict[edge_class]

        idx_original = np.random.randint(len(original_idcs))
        idx_edge     = np.random.randint(len(edge_idcs))
        
        original, original_label = self.dataset.__getitem__(original_idcs[idx_original])
        im      , edge_label     = self.dataset.__getitem__(edge_idcs[idx_edge])
        im_np = np.array(im)
        edge_np = cv2.Canny(im_np,0,0)
        edge = Image.fromarray(edge_np)
        
        if self.transform:
            edge     = self.transform(edge)
            original = self.transform(original)

        return original, edge, original_label, edge_label #TODO: double the label array?
