# Databricks notebook source
# MAGIC %md
# MAGIC # DSV — First-Time-Right risk classifier
# MAGIC Trains a gradient-boosted classifier on `dsv.silver.bookings_clean` to predict the
# MAGIC probability an incoming booking will NOT be first-time-right (needs manual correction).
# MAGIC Logs to MLflow, registers in Unity Catalog (`dsv.ml.ftr_risk_classifier`), and writes a
# MAGIC text metrics report to the `dsv.ml.eval` volume (committed as evidence).

# COMMAND ----------

# MAGIC %pip install mlflow scikit-learn
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import mlflow, mlflow.sklearn
from mlflow.models.signature import infer_signature
from pyspark.sql import functions as F
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (classification_report, confusion_matrix,
                             roc_auc_score, average_precision_score)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

CATALOG = "dsv"
UC_MODEL = f"{CATALOG}.ml.ftr_risk_classifier"
CATEGORICAL = ["mode", "channel", "customer_type", "origin_hub", "destination_hub", "service_code"]
NUMERIC = ["lead_time_days", "weight_kg", "volume_m3", "capacity_utilization", "is_international"]
TARGET = "needs_correction"

mlflow.set_registry_uri("databricks-uc")

# COMMAND ----------

df = spark.table(f"{CATALOG}.silver.bookings_clean") \
    .withColumn("needs_correction", (~F.col("first_time_right")).cast("int")) \
    .withColumn("is_international", F.col("is_international").cast("int"))
pdf = df.select(*(CATEGORICAL + NUMERIC + [TARGET])).na.fill(0.0, subset=NUMERIC).toPandas()
print("rows:", len(pdf), "positive rate:", pdf[TARGET].mean())

# COMMAND ----------

X = pdf[CATEGORICAL + NUMERIC]
y = pdf[TARGET]
X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)

pre = ColumnTransformer([
    ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
    ("num", StandardScaler(), NUMERIC),
])
clf = Pipeline([("pre", pre),
                ("lr", LogisticRegression(max_iter=1000, class_weight="balanced", C=1.0))])

with mlflow.start_run(run_name="ftr_risk_classifier") as run:
    clf.fit(X_tr, y_tr)
    proba = clf.predict_proba(X_te)[:, 1]
    pred = (proba >= 0.5).astype(int)
    auc = roc_auc_score(y_te, proba); ap = average_precision_score(y_te, proba)
    report = classification_report(y_te, pred, digits=3)
    cm = confusion_matrix(y_te, pred)

    mlflow.log_params({"model": "LogisticRegression", "C": 1.0,
                       "class_weight": "balanced", "max_iter": 1000,
                       "n_train": len(X_tr), "n_test": len(X_te)})
    mlflow.log_metrics({"roc_auc": float(auc), "avg_precision": float(ap),
                        "positive_rate": float(y.mean())})
    sig = infer_signature(X_te, proba)
    mlflow.sklearn.log_model(clf, artifact_path="model", signature=sig,
                             registered_model_name=UC_MODEL, input_example=X_te.head(3))
    run_id = run.info.run_id

    lines = ["=== DSV FTR Risk Classifier — training metrics ===",
             f"MLflow run_id: {run_id}", f"UC model: {UC_MODEL}",
             f"train rows: {len(X_tr):,}   test rows: {len(X_te):,}",
             "target = needs_correction (1 = not first-time-right)",
             f"positive rate (test): {y_te.mean():.4f}", "",
             f"ROC AUC:        {auc:.4f}", f"Avg precision:  {ap:.4f}", "",
             "Classification report:", report,
             "Confusion matrix [[TN FP][FN TP]]:", str(cm)]
    report_text = "\n".join(lines)
    print(report_text)
    dbutils.fs.put("/Volumes/dsv/ml/eval/ftr_metrics.txt", report_text, overwrite=True)

# COMMAND ----------

from mlflow.tracking import MlflowClient
c = MlflowClient()
mv = c.search_model_versions(f"name='{UC_MODEL}'")
latest = max(int(m.version) for m in mv)
c.set_registered_model_alias(UC_MODEL, "champion", latest)
print(f"Set alias champion -> {UC_MODEL} v{latest}")
