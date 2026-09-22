"""
DSV Data Workbench — First-Time-Right (FTR) risk classifier.

Predicts the probability that an incoming booking will NOT be first-time-right
(i.e. will require manual correction / amendment). This lets DSV's "AI factory"
route risky bookings for pre-emptive checks before they hit carrier space
allocation — the core of the Booking Quality automation initiative.

Runs as a Databricks notebook / job on the target workspace:
  * reads features from dsv.silver.bookings_clean
  * trains a gradient-boosted classifier, logs to MLflow
  * registers the model in Unity Catalog (dsv.ml.ftr_risk_classifier)
  * writes a text metrics report used as committed evidence

The feature set deliberately uses only fields known AT BOOKING TIME (channel,
mode, lane, customer type, lead time, capacity) — not the post-hoc quality flags —
so the model is usable for real-time scoring.
"""
from __future__ import annotations

import mlflow
import mlflow.sklearn
from mlflow.models.signature import infer_signature
from pyspark.sql import functions as F
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (classification_report, confusion_matrix,
                             roc_auc_score, average_precision_score)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

CATALOG = "dsv"
UC_MODEL = f"{CATALOG}.ml.ftr_risk_classifier"

CATEGORICAL = ["mode", "channel", "customer_type", "origin_hub",
               "destination_hub", "service_code"]
NUMERIC = ["lead_time_days", "weight_kg", "volume_m3", "capacity_utilization",
           "is_international"]
TARGET = "needs_correction"  # 1 = NOT first-time-right


def load_features(spark):
    df = spark.table(f"{CATALOG}.silver.bookings_clean")
    df = df.withColumn("needs_correction", (~F.col("first_time_right")).cast("int"))
    df = df.withColumn("is_international", F.col("is_international").cast("int"))
    cols = CATEGORICAL + NUMERIC + [TARGET]
    pdf = df.select(*cols).na.fill(0.0, subset=NUMERIC).toPandas()
    return pdf


def main():
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()

    mlflow.set_registry_uri("databricks-uc")
    pdf = load_features(spark)

    X = pdf[CATEGORICAL + NUMERIC]
    y = pdf[TARGET]
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y)

    pre = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
    ], remainder="passthrough")

    clf = Pipeline([
        ("pre", pre),
        ("gbt", HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.08, max_depth=6,
            l2_regularization=1.0, random_state=42)),
    ])

    with mlflow.start_run(run_name="ftr_risk_classifier") as run:
        clf.fit(X_tr, y_tr)
        proba = clf.predict_proba(X_te)[:, 1]
        pred = (proba >= 0.5).astype(int)

        auc = roc_auc_score(y_te, proba)
        ap = average_precision_score(y_te, proba)
        report = classification_report(y_te, pred, digits=3)
        cm = confusion_matrix(y_te, pred)

        mlflow.log_params({
            "model": "HistGradientBoostingClassifier",
            "max_iter": 200, "learning_rate": 0.08, "max_depth": 6,
            "n_train": len(X_tr), "n_test": len(X_te),
        })
        mlflow.log_metrics({
            "roc_auc": float(auc),
            "avg_precision": float(ap),
            "positive_rate": float(y.mean()),
        })

        sig = infer_signature(X_te, proba)
        mlflow.sklearn.log_model(
            clf, artifact_path="model", signature=sig,
            registered_model_name=UC_MODEL,
            input_example=X_te.head(3),
        )

        # ---- text evidence report -------------------------------------------
        lines = []
        lines.append("=== DSV FTR Risk Classifier — training metrics ===")
        lines.append(f"MLflow run_id: {run.info.run_id}")
        lines.append(f"UC model: {UC_MODEL}")
        lines.append(f"train rows: {len(X_tr):,}   test rows: {len(X_te):,}")
        lines.append(f"target = needs_correction (1 = not first-time-right)")
        lines.append(f"positive rate (test): {y_te.mean():.4f}")
        lines.append("")
        lines.append(f"ROC AUC:        {auc:.4f}")
        lines.append(f"Avg precision:  {ap:.4f}")
        lines.append("")
        lines.append("Classification report:")
        lines.append(report)
        lines.append("Confusion matrix [ [TN FP] [FN TP] ]:")
        lines.append(str(cm))
        report_text = "\n".join(lines)
        print(report_text)

        # persist to a UC volume so it can be pulled into the repo as evidence
        dbutils.fs.put(  # noqa: F821  (dbutils available in Databricks)
            "/Volumes/dsv/ml/eval/ftr_metrics.txt", report_text, overwrite=True)

    print(f"\nRegistered {UC_MODEL}. Set alias 'champion' to deploy for serving.")


if __name__ == "__main__":
    main()
