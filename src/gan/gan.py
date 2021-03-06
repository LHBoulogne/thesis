import sys
import os
import torch.nn.functional as F


from data.coupled import *
from data.combined import *
from data.mnist import *
from data.usps import *
from data.celeba import *

from vis.visualizer import *
from vis import errorplot

from gan.trainer import *
from gan.auxiliary.auxiliary import rescale
import utils

from gan.auxiliary.sample import sample_c

class GAN():
    def __init__(self, config):
        self.config = config
        self.init_generator()
        self.init_discriminator()
        if not os.path.exists(config.savefolder):
            os.mkdir(config.savefolder)

    def init_generator(self):
        module_name = "gan.model.generator." + self.config.generator
        __import__(module_name, fromlist=["*"])
        mod = sys.modules[module_name]
        self.G = mod.Generator(self.config)
        utils.cuda(self.G)

    def init_discriminator(self):
        module_name = "gan.model.discriminator." + self.config.discriminator
        __import__(module_name, fromlist=["*"])
        mod = sys.modules[module_name]
        self.D = mod.Discriminator(self.config)
        utils.cuda(self.D)
    
    def save(self, epoch=None):
        epstr = ''
        if not epoch is None:
            epstr = str(epoch) + '_'
        torch.save(self.G.state_dict(), os.path.join(self.config.savefolder, epstr + 'generator.h5'))
        torch.save(self.D.state_dict(), os.path.join(self.config.savefolder, epstr + 'discriminator.h5'))

    def load(self):
        epstr = ''
        if not self.config.load_epoch is None:
            epstr = str(self.config.load_epoch) + '_'
        gstate = torch.load(os.path.join(self.config.loadfolder, epstr+'generator.h5'), map_location=lambda storage, loc: storage)
        dstate = torch.load(os.path.join(self.config.loadfolder, epstr+'discriminator.h5'), map_location=lambda storage, loc: storage)
        self.G.load_state_dict(gstate)
        self.D.load_state_dict(dstate)
    
    def get_celeba_dataset(self, pos_labels, neg_labels, domain_label=None, domain_val=None):
        return CelebA_dataset(root='../data/celeba/', 
              labelnames=self.config.labelnames, pos_labels=pos_labels, neg_labels=neg_labels, 
              domain_label=domain_label, domain_val=domain_val,
              transform=transforms.Compose([transforms.CenterCrop(self.config.cropsize),
                                            transforms.Scale((self.config.imsize,self.config.imsize)),
                                            transforms.ToTensor(),
                                            transforms.Normalize(mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5))]),
              labeltype=self.config.labeltype)

    def get_mnist_dataset(self, labels, img_type, domain_val):
        return MNIST(labels, img_type, transform=transforms.Compose([
                                        transforms.Scale((self.config.imsize,self.config.imsize)),
                                        transforms.ToTensor(),
                                        transforms.Lambda(rescale)]),
                     root='../data/mnist/',
                     train=self.config.train,
                     domain_val=domain_val)

    def get_usps_dataset(self, labels):
        return USPS(labels, transform=transforms.Compose([
                                        transforms.Scale((self.config.imsize,self.config.imsize)),
                                        transforms.ToTensor(),
                                        transforms.Lambda(rescale)]),
                     root='../data/usps/',
                     train=self.config.train)

    def get_digit_dataset(self, labels, dataname, domain_val=None) :
        if dataname == 'USPS':
            if not domain_val is None:
                print('domain_val for USPS not implemented yet')
                return
            return self.get_usps_dataset(labels)
        if dataname == 'MNIST':
            return self.get_mnist_dataset(labels, 'original', domain_val)
        if dataname == 'MNISTEDGE':
            return self.get_mnist_dataset(labels, 'diledge', domain_val)
        if dataname == 'MNISTCANNY':
            return self.get_mnist_dataset(labels, 'edge', domain_val)

    def get_dataset(self):
        if self.config.coupled and self.config.combined:
            raise RuntimeError("invalid combination: coupled == True  and  combined == True")
        if self.config.coupled or self.config.combined: 
            if self.config.dataname == "CelebA":
                dataset1 = self.get_celeba_dataset(self.config.labels1, self.config.labels1_neg, self.config.domainlabel, 0)
                dataset2 = self.get_celeba_dataset(self.config.labels2, self.config.labels2_neg, self.config.domainlabel, 1)
            else:
                dataset1 = self.get_digit_dataset(self.config.labels1, self.config.dataname, 0)
                dataset2 = self.get_digit_dataset(self.config.labels2, self.config.dataname2,1)
            
            if self.config.coupled:
                dataset = CoupledDataset(self.config, dataset1, dataset2)
            else:
                dataset = CombinedDataset(dataset1, dataset2)

        else :
            if self.config.dataname == "CelebA":
                dataset = self.get_celeba_dataset(self.config.labels1, self.config.labels1_neg)
            else :
                dataset = self.get_digit_dataset(self.config.labels1, self.config.dataname)

        return dataset

    def make_snapshot(self, epoch, batch, trainer, imgsaver):
        self.G.eval()
        self.D.eval()

        trainer.save_error()

        if self.config.visualize_training:
            if self.config.use_generator:
                imgsaver.save_training_imgs(epoch, batch, self.G)
            errorplot.save_error_plots(trainer.get_error_storage(), self.config)
        self.save()

        self.G.train()
        self.D.train()



    def train(self):
        dataset = self.get_dataset()
        dataloader = torch.utils.data.DataLoader(dataset, 
            batch_size=self.config.mini_batch_size, shuffle=True, num_workers=self.config.dloadworkers)

        imgsaver = Visualizer(self.config)
        trainer = GANTrainer(self.config, self.G, self.D)

        epoch = 0
        steps_without_G_update = 0
        c_fake = None
        self.D.train()
        self.G.train()
        while epoch < self.config.epochs:
            print("Epoch: "+str(epoch+1)+ "/" + str(self.config.epochs) + ' '*10)

            for batch, data in enumerate(dataloader) :
                if batch%self.config.snap_step == 0:
                    self.make_snapshot(epoch, batch, trainer, imgsaver)
                
                print("\rBatch " + str(batch))
                
                if self.config.auxclas :
                    c_fake = sample_c(self.config, dataset)
                trainer.next_step(data, c_fake) # Using the same c_fake for generator and discriminator update

                if trainer.update_discriminator(self.G, self.D):
                    steps_without_G_update += 1
                #Allow for multiple updates of D with respect to G
                
                if self.config.use_generator and steps_without_G_update >= self.config.k: 
                    steps_without_G_update = 0
                    for it in range(self.config.G_updates):
                        g_updated = False
                        while not g_updated:
                            g_updated = trainer.update_generator(self.G, self.D)

            self.make_snapshot(epoch, batch+1, trainer, imgsaver)
            self.save(epoch)
            epoch += 1

    #Only works for digits now
    def test_auxclas(self, dataset, eval_d, num):
        dataloader = torch.utils.data.DataLoader(dataset, 
            batch_size=self.config.mini_batch_size, shuffle=True, num_workers=3)

        count = {}
        correct = {}
        for cat_idx, classes in enumerate(self.config.categories):
            count[cat_idx] = np.zeros(classes)
            correct[cat_idx] = np.zeros(classes)

        print("Testing auxiliary classifier", num, ':')
        for batch, data in enumerate(dataloader):
            if batch%classes == 0:
                print('\r', '%.2f'%(100 * batch / len(dataloader)),'%', end='\r')

            # get disc input
            x, c = utils.cuda(data) #read out data tuple
            out = eval_d(Variable(x))

            # get predictions
            for cat_idx, classes in enumerate(self.config.categories):
                cond = c[:,cat_idx]
                prd = out[0][1][cat_idx].data
                _, predicted = torch.max(prd, 1)

                count[cat_idx] += [(cond == it).sum() for it in range(classes)]
                for it in range(classes):
                    idcs = (cond == it).nonzero()
                    if len(idcs) != 1: 
                        idcs = idcs.squeeze()
                    if len(idcs)>0:
                        correct[cat_idx][it] += (cond[idcs] == predicted[idcs]).sum() 

        print("Accuracy for dataset",num, ':')
        for cat_idx, classes in enumerate(self.config.categories):
            print("Class nr" ,cat_idx, 'with', classes, 'categories:')
            print('count:\t', count[cat_idx])
            acc = [(100*correct[cat_idx][it]/count[cat_idx][it]) for it in range(classes)]
            print('acc:\t', ['%.2f' % x for x in acc])
            tot_count = count[cat_idx].sum()
            tot_acc = sum([count[cat_idx][it]*acc[it] for it in range(classes)])/tot_count
            print('Total:')
            print('count:\t', tot_count)
            print('acc:\t', '%.2f' % tot_acc, '\n')

    def test(self):
        self.G.eval()
        self.D.eval()

        if self.config.use_generator:
            imgsaver = Visualizer(self.config)
            imgsaver.save_test_imgs(self.G)

        if self.config.auxclas:
            dataset = self.get_dataset()

            if self.config.coupled:
                dsets = [dataset.dataset1, dataset.dataset2]
                eval_d_a = lambda x: self.D(inp_a=x)
                eval_d_b = lambda x: self.D(inp_b=x)
                eval_ds = [eval_d_a, eval_d_b]
            else :
                dsets = [dataset]
                eval_ds = [lambda x: self.D(inp_a=x)]

            for it in range(len(dsets)):
                self.test_auxclas(dsets[it], eval_ds[it], it)

        self.G.train()
        self.D.train()
