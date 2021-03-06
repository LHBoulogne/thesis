import torch
import torch.nn as nn
from gan.model.helper.weight_init import *
from gan.model.helper.layers import *

class Discriminator(nn.Module):
    def __init__(self, config):
        super(Discriminator, self).__init__() 
        self.conditional = config.conditional
        self.auxclas = config.auxclas
        self.clen = 0
        if self.conditional:
            self.imsize = config.imsize
            self.clen = sum(config.categories)
        if self.auxclas:
            self.numcats = len(config.categories)

        self.first_a = self.first_layers(config)
        
        if config.coupled:
            self.first_b = self.first_layers(config)
        
        layers = ()
        for it in range(config.blocks):
            mult = 2**it
            layers += (
                nn.Conv2d(config.d_dim*mult,  config.d_dim*mult*2, 5, stride=2, padding=2, bias=False),
                Norm2d(config.d_dim*mult*2, config.d_norm),
                Activation(config.d_act)
                )

        self.main = nn.Sequential(*layers)

        mult = 2**config.blocks
        prd_src_layers = (nn.Conv2d(config.d_dim * mult, 1, 4), Reshape(-1, 1),)
        if config.algorithm != 'wgan_gp':
            prd_src_layers += (nn.Sigmoid(),)
        self.predict_src = nn.Sequential(*prd_src_layers)

        if self.auxclas:
            self.predict_class = []
            for it in range(self.numcats):
                self.predict_class += nn.Sequential(
                    nn.Conv2d(config.d_dim * mult, config.categories[it], 4),
                    Reshape(-1, config.categories[it])
                    )
            self.init_dummy = nn.Sequential(*self.predict_class) #to apply weight initialization

        weight_init(self, config.weight_init)

    def first_layers(self, config):
        return nn.Sequential(
            nn.Conv2d(config.imgch+self.clen, config.d_dim, 5, stride=2, padding=2),
            Activation(config.d_act)
        )

    def single_forward(self, inp, first):
        hidden = first(inp)
        hidden = self.main(hidden)
        s = self.predict_src(hidden)
        if self.auxclas:
            c = ()
            for it in range(self.numcats):
                c += (self.predict_class[it](hidden),)
            return (s,c)
        return (s,)

    def forward(self, inp_a=None, inp_b=None, c_a=None, c_b=None):
        if not inp_a is None:
            if not c_a is None:
                c_a = c_a.unsqueeze(2).unsqueeze(3).expand(c_a.size(0), c_a.size(1), inp_a.size(3), inp_a.size(4))
                inp_a = torch.cat([inp_a, c_a], 1)
            out_a = self.single_forward(inp_a, self.first_a)

        if not inp_b is None:
            if not c_b is None:
                c_b = c_b.unsqueeze(2).unsqueeze(3).expand(c_b.size(0), c_b.size(1), inp_b.size(3), inp_b.size(4))
                inp_b = torch.cat([inp_b, c_b], 1)
            out_b = self.single_forward(inp_b, self.first_b)

            if not inp_a is None:
                return (out_a, out_b)
            return (out_b,)
            
        return (out_a,)