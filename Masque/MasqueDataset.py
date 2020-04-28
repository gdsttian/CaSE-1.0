from torch.utils.data import Dataset
from common.Utils import *
from torch.nn.utils.rnn import pad_sequence
import torch.nn.functional as F

def span_label(inputs, output, id2vocab, vocab_freq, max_span_size=4):
    output_list = output.tolist()
    weights=[]
    freqs=[]
    for input in inputs:
        weights_ = []
        freqs_=[]
        for i in range(max_span_size):
            size=i + 2
            step=1
            span=input.unfold(0, size, step)

            span_list = span.tolist()

            weight = torch.tensor([len(set(seg).intersection(output_list)) for seg in span_list]).float().detach()
            weights_.append(weight)
            freq = torch.tensor([sum([vocab_freq.get(id, 0) for id in seg]) for seg in span_list]).float().detach()
            freqs_.append(freq)

        weights_ = torch.cat(weights_, dim=0)
        weights.append(weights_)
        freqs_ = torch.cat(freqs_, dim=0)
        freqs.append(freqs_)

    weights=torch.stack(weights)
    freqs = torch.stack(freqs)
    return freqs, weights

class MasqueDataset(Dataset):
    def __init__(self, samples, query, passage, vocab2id, id2vocab, vocab_freq, num_passage=10, context_len=20, passage_len=200, max_span_size=4, answer_len=80, n=1E10, sample_tensor=None):
        super(MasqueDataset, self).__init__()

        if sample_tensor is None:
            self.context_len = context_len
            self.passage_len = passage_len
            self.num_passage = num_passage
            self.answer_len = answer_len
            self.max_span_size = max_span_size

            self.samples = samples
            self.query = query
            self.passage = passage
            self.vocab2id = vocab2id
            self.id2vocab=id2vocab
            self.vocab_freq=vocab_freq
            self.n = n

            self.sample_tensor=[]
            self.load()
        else:
            self.samples = samples
            self.answer_file = None
            self.qrel_file = None
            self.sample_tensor =sample_tensor
            self.len=len(sample_tensor)
        print('data size: ', self.len)

    def load(self):
        for id in range(len(self.samples)):
            sample=self.samples[id]
            id_tensor=torch.tensor([id]).long()

            contexts = [self.query[cid] for cid in sample['context_id']]
            context = []
            for q in contexts:
                context += q
            query = [CLS_WORD] + context +[SEP_WORD] + self.query[sample['query_id']]
            if len(query)>self.context_len:
                query = query[-self.context_len:]
            elif len(query)<self.context_len:
                query = query + [PAD_WORD]*(self.context_len - len(query))
            query_tensor = torch.tensor(
                [self.vocab2id.get(w) if w in self.vocab2id else self.vocab2id[UNK_WORD] for w in query],
                requires_grad=False).long()

            passage = []
            for pid in sample['passage_pool_id']:
                if pid in self.passage:
                    p=[CLS_WORD]+self.passage[pid]+[SEP_WORD]
                    if len(p)>self.passage_len:
                        p=p[:self.passage_len-1]+[SEP_WORD]
                    elif len(p)<self.passage_len:
                        p = p + [PAD_WORD] * (self.passage_len - len(p))
                    passage.append(p)
            while len(passage)<self.num_passage:
                passage.append([CLS_WORD]+[SEP_WORD]+[PAD_WORD]*(self.passage_len-2))
            passage_tensor = [torch.tensor([self.vocab2id.get(w) if w in self.vocab2id else self.vocab2id[UNK_WORD] for w in p], requires_grad=False).long() for p in passage]
            passage_tensor = torch.stack(passage_tensor)

            passage_label_tensor = [torch.tensor([sample['passage_pool_id'].index(pid)], requires_grad=False).long() for pid in sample['passage_id']]

            response= (sample['answer']+[EOS_WORD])[:self.answer_len]
            response_tensor =torch.tensor([self.vocab2id.get(w) if w in self.vocab2id else self.vocab2id[UNK_WORD] for w in response], requires_grad=False).long()

            span_freq_tensor, span_weight_tensor = span_label(passage_tensor, response_tensor, self.id2vocab, self.vocab_freq, self.max_span_size)

            copy_source=[]
            # for c in contexts:
            #     copy_source+=c
            copy_source+=query
            for p in passage:
                copy_source+=p
            source_map_tensor = torch.tensor([self.vocab2id.get(w, self.vocab2id.get(UNK_WORD)) for w in copy_source], requires_grad=False).long()

            self.sample_tensor.append([id_tensor, query_tensor, passage_tensor, response_tensor, passage_label_tensor, span_freq_tensor, span_weight_tensor, source_map_tensor])
            self.len = id + 1
            if id>=self.n:
                break

    def __getitem__(self, index):
        sample= self.sample_tensor[index]
        return [sample[0], sample[1], sample[2], sample[3], sample[4][random.randint(0, len(sample[4]) - 1)], sample[5], sample[6], sample[7]]

    def __len__(self):
        return self.len

    def context_id(self,id):
        return self.samples[id]['context_id']

    def query_id(self,id):
        return self.samples[id]['query_id']

    def passage_id(self,id):
        return self.samples[id]['passage_id']

    def pool(self, id):
        return self.samples[id]['passage_pool_id']

def collate_fn(data):
    id, query, passage, response, passage_label, span_freq, span_weight, source_map = zip(*data)

    return {'id': torch.cat(id),
            'query': torch.stack(query).unsqueeze(1),
            'passage': torch.stack(passage),
            'response': pad_sequence(response, batch_first=True),
            'passage_label': torch.cat(passage_label),
            'span_frequency': torch.stack(span_freq),
            'span_overlap': torch.stack(span_weight),
            'source_map': pad_sequence(source_map, batch_first=True)}