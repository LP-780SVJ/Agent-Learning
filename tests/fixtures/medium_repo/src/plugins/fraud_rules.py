"""Fraud rule plugin."""


class FraudRulePlugin:
    def evaluate(self, payment: dict) -> bool:
        return payment.get("risk_score", 0) > 80

