from dataclasses import dataclass, field

from codeteam.usage.pricing import ModelPricing, TokenCost, calculate_cost


@dataclass(frozen=True)# 已经记到账本里的记录，不应该被随便修改。
class UsageRecord:
    step_index: int
    model: str
    input_tokens: int
    output_tokens: int
    cost: TokenCost

@dataclass
class UsageTracker:# 所有模型调用记录的列表
    records: list[UsageRecord] = field(default_factory=list)

    def record_step(
        self,
        step_index: int,
        model: str,
        input_tokens: int,
        output_tokens: int,
        pricing: dict[str, ModelPricing] | None = None,
    ) -> UsageRecord:
        """
        记录一次模型调用
        """
        cost = calculate_cost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            pricing=pricing,
        )

        record = UsageRecord(
            step_index=step_index,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
        )
        self.records.append(record)# 把这一条记录加到当前账本里
        return record

    def total_input_tokens(self) -> int:
        """计算所有记录的输入token总数"""
        return sum(record.input_tokens for record in self.records)

    def total_output_tokens(self) -> int:
        """计算所有记录的输出token总数"""
        return sum(record.output_tokens for record in self.records)

    def total_tokens(self) -> int:
        """计算所有记录的总token数"""
        return self.total_input_tokens() + self.total_output_tokens()

    def total_cost(self) -> float:
        """计算所有记录的总成本"""
        return sum(record.cost.total_cost for record in self.records)

    