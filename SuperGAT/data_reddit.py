import os
import os.path as osp
import random
from typing import List

import torch
import numpy as np
import scipy.sparse as sp
from torch_sparse import coalesce
from torch_geometric.data import (InMemoryDataset, Data, download_url,
                                  extract_zip)
from tqdm import trange

from data_sampler import MyNeighborSampler
from utils import s_join


class MyReddit(InMemoryDataset):
    r"""The Reddit dataset from the `"Inductive Representation Learning on
    Large Graphs" <https://arxiv.org/abs/1706.02216>`_ paper, containing
    Reddit posts belonging to different communities.

    Args:
        root (string): Root directory where the dataset should be saved.
        transform (callable, optional): A function/transform that takes in an
            :obj:`torch_geometric.data.Data` object and returns a transformed
            version. The data object will be transformed before every access.
            (default: :obj:`None`)
        pre_transform (callable, optional): A function/transform that takes in
            an :obj:`torch_geometric.data.Data` object and returns a
            transformed version. The data object will be transformed before
            being saved to disk. (default: :obj:`None`)
        pre_filter (callable, optional): A function that takes in an
            :obj:`torch_geometric.data.Data` object and returns a boolean
            value, indicating whether the data object should be included in the
            final dataset. (default: :obj:`None`)
    """

    url = 'https://s3.us-east-2.amazonaws.com/dgl.ai/dataset/reddit.zip'

    def __init__(self, root,
                 sampling_size: List[int], batch_size: int, neg_sample_ratio: float, num_version: int,
                 shuffle=True,
                 transform=None, pre_transform=None, pre_filter=None):
        self.batch_size = batch_size
        self.sampling_size = sampling_size
        self.neg_sample_ratio = neg_sample_ratio
        self.num_version = num_version
        self.shuffle = shuffle

        super(MyReddit, self).__init__(root, transform, pre_transform, pre_filter)

        self.data_xy = torch.load(self.processed_paths[0])
        self.data, self.slices = torch.load(self.processed_paths[1])
        self.num_batches_per_epoch = int(torch.load(self.processed_paths[2]))
        self.batch_set_order = []

    @property
    def raw_file_names(self):
        return ['reddit_data.npz', 'reddit_graph.npz']

    @property
    def processed_dir(self):
        return osp.join(self.root, 'my_processed_{}'.format(s_join("_", self.sampling_size)))

    @property
    def processed_file_names(self):
        return ['data.pt', 'batch.pt', 'num_batches_per_epoch.pt']

    def download(self):
        path = download_url(self.url, self.raw_dir)
        extract_zip(path, self.raw_dir)
        os.unlink(path)

    def process(self):
        data = np.load(osp.join(self.raw_dir, 'reddit_data.npz'))
        x = torch.from_numpy(data['feature']).to(torch.float)
        y = torch.from_numpy(data['label']).to(torch.long)
        split = torch.from_numpy(data['node_types'])

        adj = sp.load_npz(osp.join(self.raw_dir, 'reddit_graph.npz'))
        row = torch.from_numpy(adj.row).to(torch.long)
        col = torch.from_numpy(adj.col).to(torch.long)
        edge_index = torch.stack([row, col], dim=0)
        edge_index, _ = coalesce(edge_index, None, x.size(0), x.size(0))

        data = Data(x=x, edge_index=edge_index, y=y)
        data.train_mask = split == 1
        data.val_mask = split == 2
        data.test_mask = split == 3

        _loader = MyNeighborSampler(
            data=data, batch_size=self.batch_size, bipartite=False, shuffle=True,
            size=self.sampling_size, num_hops=len(self.sampling_size),
            use_negative_sampling=True, neg_sample_ratio=self.neg_sample_ratio,
            drop_last=True,
        )
        # Data(b_id=[512], e_id=[52765], edge_index=[2, 52765], n_id=[40040],
        #      neg_edge_index=[2, 26382], sub_b_id=[512])
        print("Now batch sampling...")
        _batch_list = []
        for _i in trange(self.num_version):

            _batch_list += [_b for _b in _loader(data.train_mask)]

            if _i == 0:
                torch.save(len(_batch_list), self.processed_paths[2])

        torch.save(self.collate(_batch_list), self.processed_paths[1])

        del data.train_mask
        del data.edge_index
        torch.save(data, self.processed_paths[0])

    def __iter__(self):
        self.index = 0

        if len(self.batch_set_order) == 0:
            self.batch_set_order = list(range(self.num_version))
            random.shuffle(self.batch_set_order)

        batch_start_idx = self.batch_set_order.pop(0) * self.num_batches_per_epoch
        self.batch_order = list(range(batch_start_idx, batch_start_idx + self.num_batches_per_epoch))
        if self.shuffle:
            random.shuffle(self.batch_order)

        return self

    def __next__(self):
        if self.index >= self.num_batches_per_epoch:
            raise StopIteration
        o = self.__getitem__(self.batch_order[self.index])
        self.index += 1
        return o

    def __repr__(self):
        return '{}()'.format(self.__class__.__name__)


if __name__ == '__main__':
    mr = MyReddit("~/graph-data/reddit",
                  sampling_size=[10, 10], batch_size=512,
                  neg_sample_ratio=0.5, num_version=5)
    print(mr.data_xy)
    for b in mr:
        print(b)
        break
