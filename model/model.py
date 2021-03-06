import torch
import torch.nn as nn
from torch.nn.init import orthogonal_, zeros_, xavier_normal_
from torch.nn.utils.rnn import pad_packed_sequence


class SSAREncoder(nn.Module):
    def __init__(self, ResNet):
        super(SSAREncoder, self).__init__()
        self.conv1 = ResNet.conv1
        self.bn1 = ResNet.bn1
        self.relu = ResNet.relu
        self.maxpool = ResNet.maxpool
        self.layer1 = ResNet.layer1
        self.layer2 = ResNet.layer2
        self.conv2 = nn.Conv2d(128, 128, 3, 2, 1)
        self.bn2 = nn.BatchNorm2d(128)
        self.conv3 = nn.Conv2d(128, 256, 3, 2, 1)
        self.bn3 = nn.BatchNorm2d(256)

    def forward(self, x):
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.conv2(x)
        x = self.bn2(x)
        x = self.relu(x)
        x = self.conv3(x)
        x = self.bn3(x)
        x = self.relu(x)

        return x


class SSARDecoder(nn.Module):

    def __init__(self):
        super(SSARDecoder, self).__init__()
        self.deconv0 = nn.ConvTranspose2d(256, 64, 4, 2, 1)
        self.deconv1 = nn.ConvTranspose2d(64, 32, 4, 2, 1)
        self.deconv2 = nn.ConvTranspose2d(32, 16, 4, 2, 1)
        self.deconv3 = nn.ConvTranspose2d(16, 8, 4, 2, 1)
        self.deconv4 = nn.ConvTranspose2d(8, 2, 4, 2, (2, 1))

    def forward(self, x):

        x = self.deconv0(x)
        x = self.deconv1(x)
        x = self.deconv2(x)
        x = self.deconv3(x)
        mask = self.deconv4(x)

        return mask


class SSAREmbeddingGenerator(nn.Module):

    def __init__(self):
        super(SSAREmbeddingGenerator, self).__init__()
        self.linear0 = nn.Linear(7168, 2048)
        self.bn = nn.BatchNorm1d(2048)
        self.linear1 = nn.Linear(2048, 83)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):

        batch_size, depth, width, height = x.size(0), x.size(1), x.size(2), x.size(3)
        encoded_features = x.view(batch_size, depth*width*height)
        encoded_features = self.linear0(encoded_features)
        encoded_features = self.bn(encoded_features)
        encoded_features = self.relu(encoded_features)
        encoded_features = self.linear1(encoded_features)
        return encoded_features


class SSARLSTM(nn.Module):

    def __init__(self, input_size, number_of_classes, batch_size, dropout):
        super(SSARLSTM, self).__init__()
        self.relu = nn.ReLU(inplace=True)
        self.input_size = input_size
        self.hidden_size = int(input_size)
        self.number_of_classes = number_of_classes
        self.batch_size = batch_size
        self.lstm1 = nn.LSTM(input_size, self.hidden_size, batch_first=True, dropout=dropout)
        self.lstm2 = nn.LSTM(self.hidden_size, self.hidden_size, batch_first=True, dropout=dropout)
        self.lstm3 = nn.LSTM(self.hidden_size, self.hidden_size, batch_first=True, dropout=dropout)
        self.lstm4 = nn.LSTM(self.hidden_size, self.hidden_size, batch_first=True, dropout=dropout)
        self.fc = nn.Linear(self.hidden_size, self.number_of_classes)
        self.init_lstm_weights()

    def init_lstm_weights(self):
        # Xavier Normal for input weights
        orthogonal_(self.lstm1.all_weights[0][0])
        xavier_normal_(self.lstm2.all_weights[0][0])
        orthogonal_(self.lstm3.all_weights[0][0])
        xavier_normal_(self.lstm4.all_weights[0][0])
        # Orthogonal for recurrent weights
        orthogonal_(self.lstm1.all_weights[0][1])
        xavier_normal_(self.lstm2.all_weights[0][1])
        orthogonal_(self.lstm3.all_weights[0][1])
        xavier_normal_(self.lstm4.all_weights[0][1])
        # Zeros for biases
        zeros_(self.lstm1.all_weights[0][2])
        zeros_(self.lstm1.all_weights[0][3])
        zeros_(self.lstm2.all_weights[0][2])
        zeros_(self.lstm2.all_weights[0][3])
        zeros_(self.lstm3.all_weights[0][2])
        zeros_(self.lstm3.all_weights[0][3])
        zeros_(self.lstm4.all_weights[0][2])
        zeros_(self.lstm4.all_weights[0][3])

    def forward(self, x, lengths=None):
        sequence_labels, hidden = self.lstm1(x)
        sequence_labels, hidden = self.lstm2(sequence_labels)
        sequence_labels, hidden = self.lstm3(sequence_labels)
        sequence_labels, (h_n, c_n) = self.lstm4(sequence_labels)
        if type(sequence_labels) is nn.utils.rnn.PackedSequence:
            sequence_labels, seq_lengths = pad_packed_sequence(sequence=sequence_labels, batch_first=True)
        else:
            seq_lengths = lengths
        batch_size = sequence_labels.shape[0]
        out = sequence_labels[0, seq_lengths[0] - 1, :]
        out = out.unsqueeze(dim=0)
        for i in range(1, batch_size):
            out = torch.cat((out, sequence_labels[i, seq_lengths[i] - 1, :].unsqueeze(dim=0)))

        label = self.fc(out)
        return label


class SSAR(nn.Module):

    def __init__(self, ResNet, input_size, number_of_classes, batch_size, dropout):
        super(SSAR, self).__init__()
        self.encoder = SSAREncoder(ResNet)
        self.decoder = SSARDecoder()
        self.embedding_generator = SSAREmbeddingGenerator()
        self.lstms = SSARLSTM(input_size, number_of_classes, batch_size, dropout)

    def forward(self, x, get_mask=False):
        x = self.encoder(x)

        embeddings = self.embedding_generator(x)
        lengths = [embeddings.shape[0]]
        embeddings = embeddings.unsqueeze(0)

        label = self.lstms(embeddings, lengths)

        if get_mask:
            mask = self.decoder(x)
            return mask, label
        else:
            return label
