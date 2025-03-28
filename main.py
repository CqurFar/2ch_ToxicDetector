import os
import spacy
import torch
import kagglehub
import numpy as np
import pandas as pd
import seaborn as sns
from tqdm import tqdm
import matplotlib.pyplot as plt
from wordcloud import WordCloud
from janitor import clean_names
from collections import Counter
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# # Загрузка датасета
# path = kagglehub.dataset_download(
#     handle="blackmoon/russian-language-toxic-comments",
#     path="./data")


# Кешируем модель spaCy
temp_dir = os.getenv("temp", "./")
spacy_path = os.path.join(temp_dir, "spacy_model")

spacy.require_gpu()
nlp = spacy.load("ru_core_news_sm", disable=["parser", "ner"])
nlp.to_disk(spacy_path)
nlp = spacy.load(spacy_path)

# Модель с Hugging Face
MODEL_PATH = "khvatov/ru_toxicity_detector"
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)

model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)


# Импорт датасета
def import_csv(directory="my_data_folder"):
    files = [os.path.join(directory, file) for file in os.listdir(directory) if file.endswith(".csv")]
    data_dict = {}
    na_counts = {}

    for file in files:
        df = clean_names(pd.read_csv(file, na_values=str(["N/A", "NA", ".", ""])))
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        data_name = os.path.splitext(os.path.basename(file))[0]
        data_dict[data_name] = df
        na_counts[data_name] = df.isna().sum().sum()

    na_df = pd.DataFrame(list(na_counts.items()), columns=["dataset", "na_count"])
    globals().update(data_dict)
    return na_df


# NLP-предобработка
def text_processing(text: str) -> str:
    if not isinstance(text, str):
        return ""

    text = text.lower()
    doc = nlp(text)
    tokens = np.array([token.lemma_ for token in doc
                       if not token.is_stop and not token.is_punct])

    return " ".join(tokens.tolist())


# Определение токсичности
def toxic_detector(text: str) -> float:
    with torch.no_grad():
        inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True).to(device)
        proba = torch.nn.functional.softmax(model(**inputs).logits, dim=1)
        return proba[:, 1].item()


# Обработка DataFrame
def processing(df: pd.DataFrame):
    df.rename(columns={"toxic": "labeled", "comment": "txt"}, inplace=True)

    df["txt"] = (df["txt"]
                 .astype(str)
                 .str.lower()
                 .str.replace(r"\\n|\n|\r", " ", regex=True)
                 .str.strip())

    df["txt_clean"] = list(tqdm(map(text_processing, df["txt"]),
                                total=len(df),
                                desc="NLP-предобработка"))
    df["toxic_accur"] = list(tqdm(map(toxic_detector, df["txt_clean"]),
                                  total=len(df),
                                  desc="Определение токсичности"))

    df["toxic_accur"] = (df["toxic_accur"] >= 0.33).astype("int32")
    df["labeled"] = df["labeled"].astype("int32")
    accur = (df["toxic_accur"].eq(df["labeled"])).mean() * 100
    print(f"Точность модели: {accur:.2f}%")  # 84.98%


# Аналитика
def eda_analysis(df: pd.DataFrame):
    font_path = r"C:\Windows\\Fonts\times.ttf"
    preset = {"fontsize": 14,
              "fontname": "Times New Roman"}

    # === Баланс классов ===
    plt.figure(figsize=(16.2, 10.8), dpi=100)

    sns.countplot(x=df["labeled"],
                  hue=df["labeled"],
                  legend=False,
                  palette="viridis")

    plt.title("Распределение классов (токсичность)", **preset)
    plt.xlabel("Класс", **preset)
    plt.ylabel("Кол-во", **preset)
    plt.xticks(ticks=[0, 1], labels=["Нетоксичные", "Токсичные"], **preset)

    graph_path = "./plots/01.png"
    plt.savefig(graph_path, transparent=True)
    plt.close()

    # === Длина комментариев ===
    df["txt_len"] = df["txt"].apply(lambda x: len(x.split()))
    df["txt_len"] = df["txt_len"].clip(upper=120)

    plt.figure(figsize=(18.6, 10.8), dpi=100)
    sns.histplot(df["txt_len"],
                 bins=60,
                 kde=True,
                 color="blue")

    plt.title("Распределение длины комментариев", **preset)
    plt.xlabel("Кол-во слов", **preset)
    plt.ylabel("Частота", **preset)

    graph_path = "./plots/02.png"
    plt.savefig(graph_path, transparent=True)
    plt.close()

    # === Облако слов для токсичных комментариев ===
    toxic_texts = " ".join(df.loc[df["labeled"] == 1, "txt_clean"])
    wordcloud = (WordCloud(width=1440, height=1080, background_color="white", font_path=font_path)
                 .generate(toxic_texts))

    plt.figure(figsize=(14.4, 10.8), dpi=100)
    plt.imshow(wordcloud, interpolation="lanczos")
    plt.title("Все слова из токсичных комментариев \n(лень фильтровать по словарю)", **preset)
    plt.axis("off")
    plt.subplots_adjust(top=0.9)

    graph_path = "./plots/03.png"
    plt.savefig(graph_path, transparent=True)
    plt.close()

    # === Анализ биграмм ===
    def get_bigrams(texts):
        bigrams = []
        for text in texts.dropna():
            words = text.split()
            bigrams.extend(zip(words[:-1], words[1:]))
        return Counter(bigrams).most_common(15)

    toxic_bigrams = get_bigrams(df.loc[df["labeled"] == 1, "txt_clean"])
    bigram_labels = [" ".join(pair) for pair, _ in toxic_bigrams]
    bigram_counts = [count for _, count in toxic_bigrams]

    plt.figure(figsize=(16.2, 10.8), dpi=100)
    sns.barplot(x=bigram_counts, y=bigram_labels, hue=bigram_labels, legend=False, palette="plasma")
    plt.title("Топ-15 биграмм в токсичных комментариях \n(лень фильтровать по словарю)", **preset)
    plt.xlabel("Частота", **preset)
    plt.ylabel("Биграммы", **preset)

    graph_path = "./plots/04.png"
    plt.savefig(graph_path, transparent=True)
    plt.close()


# Запуск пайплайна
import_csv("./data")
processing(globals()["ru_toxic"])
eda_analysis(globals()["ru_toxic"])
