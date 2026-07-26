from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_1m_tokens: float
    output_per_1m_tokens: float


@dataclass(frozen=True)
class TokenCost:
    model: str
    input_tokens: int
    output_tokens: int
    input_cost: float
    output_cost: float
    total_cost: float


MODEL_PRICING: dict[str, ModelPricing] = {
    "mock-model": ModelPricing(
        input_per_1m_tokens=0.10,
        output_per_1m_tokens=0.40,
    ),
}


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    pricing: dict[str, ModelPricing] | None = None,
) -> TokenCost:
    if input_tokens < 0:
        raise ValueError("input_tokens must be >= 0.")
    if output_tokens < 0:
        raise ValueError("output_tokens must be >= 0.")

    pricing_table = MODEL_PRICING if pricing is None else pricing
    if model not in pricing_table:
        raise ValueError(f"Unknown model pricing: {model}")

    model_pricing = pricing_table[model]
    input_cost = input_tokens / 1_000_000 * model_pricing.input_per_1m_tokens
    output_cost = output_tokens / 1_000_000 * model_pricing.output_per_1m_tokens

    return TokenCost(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=input_cost + output_cost,
    )
