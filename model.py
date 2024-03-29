import torch
import torch.nn as nn
import torch.nn.functional as F


def acc_loss(y, evidences, classes):
    """
    计算一个样本的预测损失项
    :param y:数据标签
    :param evidences:一个样本的所有视图的evidences
    :param classes:总的分类类别数
    :return:一个样本的L_acc(alpha_i)
    """
    alpha_a = torch.sum(evidences, dim=0, keepdim=False) + 1
    S = torch.sum(alpha_a)
    P = alpha_a / S  # 预测项P_ij
    label = F.one_hot(y, num_classes=classes)  # Y_ij
    diff = label.float() - P  # 计算 P_ij 与 Y_ij 的差值
    L_err = diff ** 2  # L_err预测损失项
    L_var = torch.mul(P, 1 - P) / (S + 1)  # L_var方差
    L_acc = torch.sum(L_err + L_var)
    return L_acc


def con_loss(evidences, a, views, classes):
    """
    计算一个样本的所有视图的一致性损失
    :param evidences: 一个样本的所有视图evidence
    :param a: 对k类的先验偏好
    :param views:视图数量
    :param classes:类别数量
    :return:一致性损失
    """
    alpha = evidences + 1
    S = torch.sum(alpha, dim=1, keepdim=True)  # 每个视图的Dirichlet strength
    B = evidences / S  # 每个视图的分类信念
    U = classes / S  # 每个视图的分类不确定性
    P = B + a * U  # 用于计算熵的每个视图的P_k
    H = -torch.sum(torch.mul(P, torch.log2(P)), dim=1, keepdim=True)
    L_con = 0.0
    for m in range(views):
        sum_E = 0.0
        for v in range(views):  # 两两组合不重复
            if m != v:
                P_mv = (P[m] + P[v]) / 2.0
                H_mv = -torch.sum(torch.mul(P_mv, torch.log2(P_mv)))
                E_mv = (H_mv - H[m] / 2.0 - H[v] / 2.0)
                sum_E = sum_E + E_mv
        sum_E = sum_E / (views - 1)
        L_con = L_con + sum_E
    return L_con


# 模型结构
class TMDLO(nn.Module):
    def __init__(self, classes, views, lambda_con, classifier_dims):
        """
        :param classes: 分类的类别数量
        :param views: 视图数量
        :param lambda_con: 一致性损失调节系数
        :param classifier_dims: 神经网络各层维度
        """
        super(TMDLO, self).__init__()
        self.views = views
        self.classes = classes
        self.lambda_con = lambda_con
        self.Classifiers = nn.ModuleList([Classifier(classifier_dims[i], self.classes) for i in
                                          range(self.views)])  # 多个视图的分类器。每个视图都有一个独立的分类器，用于处理对应视图的特征

    def infer(self, X):
        """
        一个样本的各个视图evidence的推导
        :param X: 一个样本的多视图数据
        :return: 一个样本的所有视图的evidence字典
        """
        evidences = torch.zeros((self.views, self.classes))  # 所有视图的evidence
        for v_num in range(self.views):
            evidences[v_num] = self.Classifiers[v_num](X[v_num])
        return evidences

    def forward(self, X, y):
        """
        模型的前向传播
        :param X:输入数据
        :param y:标签
        :return:一个样本的损失
        """
        evidences = self.infer(X)
        a = torch.ones((1, self.classes)) / self.classes  # 对k类的偏好系数，没有偏好设置为1/classes
        loss = 0  # 整体损失
        L_acc = acc_loss(y, evidences, self.classes)
        L_con = con_loss(evidences, a, self.views, self.classes)
        loss += (L_acc + self.lambda_con * L_con)
        return loss


# 神经网络结构
class Classifier(nn.Module):
    def __init__(self, classifier_dims, classes):
        """
        :param classifier_dims: 神经网络各层的维度，即数据集各个视角维度:[[240], [76], [216], [47], [64], [6]]
        :param classes: 输出的类别数量
        """
        super(Classifier, self).__init__()
        self.num_layers = len(classifier_dims)
        self.fc = nn.ModuleList()  # 创建了一个空的 nn.ModuleList() 对象 self.fc，用于存储神经网络的所有线性层
        for i in range(self.num_layers - 1):
            # 添加线性层，输入大小为classifier_dims[i]，输出大小为classifier_dims[i + 1]，默认使用偏置量
            self.fc.append(nn.Linear(classifier_dims[i], classifier_dims[i + 1]))
        self.fc.append(nn.Linear(classifier_dims[self.num_layers - 1], classes))  # 最后一层分类输出层
        self.fc.append(nn.Softplus())  # 激活函数层，Relu的替代方案

    def forward(self, x):
        """
        :param x: 神经网络的输入数据
        :return: 神经网络的最终输出，即经过所有线性层和激活函数后的结果
        """
        h = self.fc[0](x)  # 把输入X传递给第一个线性层
        for i in range(1, len(self.fc)):
            h = self.fc[i](h)
        return h
