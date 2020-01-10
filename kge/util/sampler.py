from kge import Config, Configurable, Dataset
import torch
from typing import Optional
import numpy as np

SLOTS = [0, 1, 2]
SLOT_STR = ["s", "p", "o"]
S, P, O = SLOTS


class KgeSampler(Configurable):
    """ Negative sampler """

    def __init__(self, config: Config, configuration_key: str, dataset: Dataset):
        super().__init__(config, configuration_key)

        # load config
        self.num_samples = torch.zeros(3, dtype=torch.int)
        self.filter_positives = torch.zeros(3, dtype=torch.bool)
        self.vocabulary_size = torch.zeros(3, dtype=torch.int)
        for slot in SLOTS:
            slot_str = SLOT_STR[slot]
            self.num_samples[slot] = self.get_option(f"num_samples_{slot_str}")
            self.filter_positives[slot] = self.get_option(
                f"filtering.{slot_str}"
            )
            self.vocabulary_size[slot] = (
                dataset.num_relations() if slot == P else dataset.num_entities()
            )
        self.dataset = dataset

        # auto config
        for slot, copy_from in [(S, O), (P, None), (O, S)]:
            if self.num_samples[slot] < 0:
                if copy_from is not None and self.num_samples[copy_from] > 0:
                    self.num_samples[slot] = self.num_samples[copy_from]
                else:
                    self.num_samples[slot] = 0

    @staticmethod
    def create(config: Config, configuration_key: str, dataset: Dataset):
        """ Factory method for sampler creation."""
        sampling_type = config.get(configuration_key + ".sampling_type")
        if sampling_type == "uniform":
            return KgeUniformSampler(config, configuration_key, dataset)
            # TODO add frequency-based/biased sampling
        else:
            # perhaps TODO: try class with specified name -> extensibility
            raise ValueError(configuration_key + ".sampling_type")

    def sample(self, spo: torch.Tensor, slot: int, num_samples: Optional[int] = None):
        """ Obtain a set of negative samples for a specified slot.

        `spo` is a batch_size x 3 tensor of positive triples. `slot` is either 0
        (subject), 1 (predicate), or 2 (object). If `num_samples` is `None`, it is set
        to the default value for the slot configured in this sampler.

        Returns a batch_size x num_samples tensor with indexes of the sampled negative
        entities (`slot`=0 or `slot`=2) or relations (`slot`=1).

        """
        if num_samples is None:
            num_samples = self.num_samples[slot]
        result = self._sample(self.vocabulary_size[slot], (spo.size(0), num_samples))
        if self.filter_positives[slot]:
            result = self._filter(result, slot, spo)
        return result

    def _sample(self, max_val: int, shape: tuple):
        """ Sample examples. """
        raise NotImplementedError()

    def _filter(self, result: torch.Tensor, slot: int, spo: torch.Tensor):
        """ Filter and resample indices until only negatives have been created. """
        spo_char = "spo"
        pair = spo_char.replace(spo_char[slot], "")
        # holding the positive indices for the respective pair
        index = self.dataset.index(f"train_{pair}_to_{spo_char[slot]}")
        cols = [0, 1, 2]
        cols.remove(slot)
        pairs = spo[:, cols]
        for i in range(spo.size(0)):
            # indices of samples that have to be sampled again
            # Note: giving np.isin a set as second argument potentially is faster
            # but conversion to a set induces costs that make things worse
            resample_idx = np.where(
                np.isin(
                    result[i],
                    index[tuple(pairs[i].tolist())]
                ) != 0
            )[0]
            # number of new samples needed
            num_new = len(resample_idx)
            new = torch.empty(num_new, dtype=torch.long)
            # number already found of the new samples needed
            num_found = 0
            num_remaining = num_new - num_found
            while True:
                if not num_remaining:
                    break
                new_samples = self._sample(
                    self.vocabulary_size[slot], (num_remaining,)
                )
                # indices of the true negatives
                tn_idx = np.where(
                    np.isin(
                        new_samples,
                        index[tuple(pairs[i].tolist())]
                    ) == 0
                )[0]
                # store the correct (true negatives) samples found
                if len(tn_idx):
                    new[num_found: num_found + len(tn_idx)] = new_samples[tn_idx]
                num_found += len(tn_idx)
                num_remaining = num_new - num_found
            result[i, resample_idx] = new
        return result


class KgeUniformSampler(KgeSampler):
    def __init__(self, config: Config, configuration_key: str, dataset: Dataset):
        super().__init__(config, configuration_key, dataset)

    def _sample(self, max_val: int, shape: tuple):
        return torch.randint(max_val, shape)

