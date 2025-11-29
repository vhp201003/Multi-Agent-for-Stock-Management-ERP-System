import os
import warnings
from datetime import datetime, timedelta

import joblib
import numpy as np
import pandas as pd

from src.typing.mcp.forecasting import (
    ForecastFilters,
    ForecastItem,
    ForecastOutput,
    ForecastSummary,
)

warnings.filterwarnings("ignore", message=".*feature names.*")


def predict_sales_forecast_v2(item_code: str, months: int = 2) -> ForecastOutput:
    """
    Predict next N months sales for a specific item using V2 model.

    Args:
        item_code (str): Item code to predict (e.g., 'RCK-0128')
        months (int): Number of months to predict (1, 2, or 3). Default: 2

    Returns:
        ForecastOutput: Standardized forecast results.
    """

    try:
        if not isinstance(months, int) or months < 1 or months > 3:
            return ForecastOutput(
                success=False,
                error="months parameter must be 1, 2, or 3",
                filters_applied=ForecastFilters(item_code=item_code, months=months),
            )

        base_dir = os.path.dirname(os.path.abspath(__file__))
        models_dir = os.path.join(base_dir, "models")

        rf_path = os.path.join(models_dir, "rf_monthly_per_item_v2_realistic.pkl")
        le_path = os.path.join(models_dir, "item_encoder_monthly_v2_realistic.pkl")
        features_path = os.path.join(models_dir, "features_monthly_v2_realistic.pkl")

        if not os.path.exists(rf_path):
            return ForecastOutput(
                success=False,
                error=f"Model file not found: {rf_path}",
                filters_applied=ForecastFilters(item_code=item_code, months=months),
            )

        rf = joblib.load(rf_path)
        le = joblib.load(le_path)
        feature_cols = joblib.load(features_path)

        item_code_upper = item_code.strip().upper()
        item_history = pd.DataFrame()

        today = datetime.now()

        month_dates = []
        current_date = today.replace(day=1) + timedelta(days=32)
        current_date = current_date.replace(day=1)

        for _ in range(months):
            month_dates.append(current_date)
            current_date = current_date.replace(day=1) + timedelta(days=32)
            current_date = current_date.replace(day=1)

        if len(item_history) > 0:
            item_avg_qty = item_history["total_qty"].mean()
            item_avg_orders = item_history["order_count"].mean()
        else:
            item_avg_qty = 0.0
            item_avg_orders = 0.0

        item_lag_1 = (
            item_history["total_qty"].iloc[-1]
            if len(item_history) > 0
            else item_avg_qty
        )
        item_lag_3 = (
            item_history["total_qty"].iloc[-3]
            if len(item_history) >= 3
            else item_avg_qty
        )
        item_lag_6 = (
            item_history["total_qty"].iloc[-6]
            if len(item_history) >= 6
            else item_avg_qty
        )

        try:
            item_encoded = le.transform([item_code_upper])[0]
        except ValueError:
            item_encoded = 0

        predictions = []

        base_trend = len(item_history)

        for month_num, predict_date in enumerate(month_dates, 1):
            year = predict_date.year
            month = predict_date.month
            quarter = (month - 1) // 3 + 1
            season = month % 4

            trend = base_trend + month_num

            if month_num == 1:
                qty_lag_1 = item_lag_1
                qty_lag_3 = item_lag_3
                qty_lag_6 = item_lag_6
                qty_lag_12 = item_avg_qty
            else:
                qty_lag_1 = predictions[-1]["predicted_qty"]
                qty_lag_3 = (
                    item_lag_3
                    if month_num <= 2
                    else predictions[-2]["predicted_qty"]
                    if len(predictions) >= 2
                    else item_lag_3
                )
                qty_lag_6 = item_lag_6
                qty_lag_12 = item_avg_qty

            ma_3 = item_avg_qty
            ma_6 = item_avg_qty
            orders_lag_1 = item_avg_orders

            trend_sq = trend**2
            X = pd.DataFrame(
                {
                    "year": [year],
                    "month": [month],
                    "quarter": [quarter],
                    "season": [season],
                    "item_encoded": [item_encoded],
                    "qty_lag_1": [qty_lag_1],
                    "qty_lag_3": [qty_lag_3],
                    "qty_lag_6": [qty_lag_6],
                    "qty_lag_12": [qty_lag_12],
                    "ma_3": [ma_3],
                    "ma_6": [ma_6],
                    "trend": [trend],
                    "trend_sq": [trend_sq],
                    "orders_lag_1": [orders_lag_1],
                }
            )

            X = X[feature_cols]

            pred_rf = max(1, rf.predict(X)[0])

            tree_preds = np.array([tree.predict(X)[0] for tree in rf.estimators_])
            std_dev = tree_preds.std()
            ci_lower = max(1, pred_rf - 1.96 * std_dev)
            ci_upper = pred_rf + 1.96 * std_dev

            if pred_rf > 15:
                demand_level = "HIGH"
            elif pred_rf > 8:
                demand_level = "MEDIUM"
            else:
                demand_level = "LOW"

            predictions.append(
                {
                    "month": month_num,
                    "month_year": predict_date.strftime("%m/%Y"),
                    "predicted_qty": round(pred_rf),
                    "confidence_lower": round(ci_lower, 2),
                    "confidence_upper": round(ci_upper, 2),
                    "std_dev": round(std_dev, 2),
                    "demand_level": demand_level,
                }
            )

        total_qty = sum(p["predicted_qty"] for p in predictions)
        avg_per_month = total_qty / len(predictions) if len(predictions) > 0 else 0

        if len(predictions) > 1:
            if predictions[-1]["predicted_qty"] > predictions[0]["predicted_qty"]:
                trend = "GROWING"
                trend_pct = round(
                    (
                        (
                            predictions[-1]["predicted_qty"]
                            - predictions[0]["predicted_qty"]
                        )
                        / predictions[0]["predicted_qty"]
                    )
                    * 100,
                    2,
                )
            elif predictions[-1]["predicted_qty"] < predictions[0]["predicted_qty"]:
                trend = "DECLINING"
                trend_pct = round(
                    (
                        (
                            predictions[0]["predicted_qty"]
                            - predictions[-1]["predicted_qty"]
                        )
                        / predictions[0]["predicted_qty"]
                    )
                    * 100,
                    2,
                )
                trend_pct = -trend_pct
            else:
                trend = "STABLE"
                trend_pct = 0.0
        else:
            trend = "N/A"
            trend_pct = 0.0

        if len(item_history) > 0:
            historical_avg = item_history["total_qty"].mean()
            if avg_per_month > historical_avg:
                vs_historical = "INCREASE"
                vs_historical_pct = round(
                    ((avg_per_month - historical_avg) / historical_avg) * 100, 2
                )
            elif avg_per_month < historical_avg:
                vs_historical = "DECREASE"
                vs_historical_pct = round(
                    ((historical_avg - avg_per_month) / historical_avg) * 100, 2
                )
                vs_historical_pct = -vs_historical_pct
            else:
                vs_historical = "STABLE"
                vs_historical_pct = 0.0
        else:
            historical_avg = 0.0
            vs_historical = "N/A"
            vs_historical_pct = 0.0

        avg_std = np.mean([p["std_dev"] for p in predictions])
        if avg_std < 1.0:
            accuracy = "HIGH (±0.77)"
        elif avg_std < 2.0:
            accuracy = "MEDIUM"
        else:
            accuracy = "LOW"

        forecast_items = [ForecastItem(**p) for p in predictions]

        summary = ForecastSummary(
            total_months=months,
            total_qty=int(total_qty),
            avg_per_month=int(avg_per_month),
            trend=trend,
            trend_pct=trend_pct,
            vs_historical=vs_historical,
            vs_historical_pct=vs_historical_pct,
            historical_avg=round(historical_avg),
            accuracy=accuracy,
            model_version="v2_realistic",
        )

        filters = ForecastFilters(item_code=item_code_upper, months=months)

        return ForecastOutput(
            success=True, items=forecast_items, summary=summary, filters_applied=filters
        )

    except Exception as e:
        return ForecastOutput(
            success=False,
            error=str(e),
            filters_applied=ForecastFilters(
                item_code=item_code.upper()
                if isinstance(item_code, str)
                else "UNKNOWN",
                months=months,
            ),
        )
