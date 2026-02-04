"""
PPO Training Script for Code Refactoring Model

This script demonstrates how to fine-tune a code generation model using
Proximal Policy Optimization (PPO) from the TRL library to improve
code refactoring quality.

Usage:
    python train_refactoring_ppo.py --model Salesforce/codet5p-770m \
        --data training_data.json --epochs 5 --batch-size 4
"""

import argparse
import json
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from trl import PPOTrainer, PPOConfig, AutoModelForSeq2SeqLMWithValueHead
from datasets import Dataset
import ast
import radon.complexity as radon_cc
import radon.metrics as radon_metrics
from typing import Dict, List
import wandb
from tqdm import tqdm


class CodeQualityReward:
    """Compute rewards based on code quality improvements"""
    
    @staticmethod
    def calculate_complexity(code: str) -> Dict:
        """Calculate code complexity metrics"""
        try:
            complexity_results = radon_cc.cc_visit(code)
            total_complexity = sum(item.complexity for item in complexity_results)
            avg_complexity = total_complexity / len(complexity_results) if complexity_results else 0
            
            mi_result = radon_metrics.mi_visit(code, multi=True)
            maintainability_index = mi_result if isinstance(mi_result, (int, float)) else 0
            
            loc = len([line for line in code.split('\n') if line.strip() and not line.strip().startswith('#')])
            
            return {
                "cyclomatic_complexity": avg_complexity,
                "total_complexity": total_complexity,
                "maintainability_index": maintainability_index,
                "loc": loc,
                "functions": len(complexity_results)
            }
        except:
            return {
                "cyclomatic_complexity": 0,
                "total_complexity": 0,
                "maintainability_index": 0,
                "loc": 0,
                "functions": 0
            }
    
    @staticmethod
    def compute_reward(original_code: str, refactored_code: str, 
                       weight_complexity: float = 0.4,
                       weight_maintainability: float = 0.3,
                       weight_conciseness: float = 0.2,
                       weight_syntax: float = 0.1) -> float:
        """
        Compute reward for refactored code
        
        Returns:
            float: Reward value (higher is better)
        """
        
        # 1. Syntax validity check
        syntax_reward = 1.0
        try:
            ast.parse(refactored_code)
        except SyntaxError:
            return -10.0  # Heavy penalty for invalid code
        
        # 2. Calculate metrics for both versions
        original_metrics = CodeQualityReward.calculate_complexity(original_code)
        refactored_metrics = CodeQualityReward.calculate_complexity(refactored_code)
        
        # 3. Complexity improvement
        if original_metrics["cyclomatic_complexity"] > 0:
            complexity_improvement = (
                original_metrics["cyclomatic_complexity"] - 
                refactored_metrics["cyclomatic_complexity"]
            ) / original_metrics["cyclomatic_complexity"]
        else:
            complexity_improvement = 0
        
        # Clip to prevent excessive rewards
        complexity_improvement = max(-1.0, min(1.0, complexity_improvement))
        
        # 4. Maintainability improvement
        maintainability_improvement = (
            refactored_metrics["maintainability_index"] - 
            original_metrics["maintainability_index"]
        ) / 100.0
        
        maintainability_improvement = max(-1.0, min(1.0, maintainability_improvement))
        
        # 5. Conciseness (LOC reduction, but not too aggressive)
        if original_metrics["loc"] > 0:
            loc_ratio = refactored_metrics["loc"] / original_metrics["loc"]
            
            # Optimal range: 0.7-1.0 (reduce by 0-30%)
            if 0.7 <= loc_ratio <= 1.0:
                conciseness_reward = (1.0 - loc_ratio) / 0.3  # Normalize to [0, 1]
            elif loc_ratio < 0.7:
                conciseness_reward = -0.5  # Penalty for over-reduction
            else:
                conciseness_reward = -0.2  # Penalty for increasing LOC
        else:
            conciseness_reward = 0
        
        # 6. Combine rewards
        total_reward = (
            weight_complexity * complexity_improvement +
            weight_maintainability * maintainability_improvement +
            weight_conciseness * conciseness_reward +
            weight_syntax * syntax_reward
        )
        
        return total_reward


class RefactoringPPOTrainer:
    """PPO Trainer for code refactoring"""
    
    def __init__(self, 
                 model_name: str = "Salesforce/codet5p-770m",
                 learning_rate: float = 1e-5,
                 batch_size: int = 4,
                 mini_batch_size: int = 1,
                 ppo_epochs: int = 4,
                 use_wandb: bool = False):
        
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {self.device}")
        
        # Load tokenizer and model
        print(f"Loading model: {model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        
        # Create model with value head for PPO
        self.model = AutoModelForSeq2SeqLMWithValueHead.from_pretrained(model_name)
        self.model = self.model.to(self.device)
        
        # Configure PPO
        self.ppo_config = PPOConfig(
            model_name=model_name,
            learning_rate=learning_rate,
            batch_size=batch_size,
            mini_batch_size=mini_batch_size,
            gradient_accumulation_steps=batch_size // mini_batch_size,
            ppo_epochs=ppo_epochs,
            optimize_cuda_cache=True,
            early_stopping=True,
            target_kl=0.1,
            seed=42,
        )
        
        self.use_wandb = use_wandb
        if use_wandb:
            wandb.init(project="code-refactoring-ppo", config=self.ppo_config.__dict__)
    
    def prepare_dataset(self, training_examples: List[Dict]) -> Dataset:
        """Prepare dataset for PPO training"""
        
        formatted_examples = []
        for example in training_examples:
            query = f"Refactor this Python code to improve quality:\n{example['original_code']}"
            
            formatted_examples.append({
                "query": query,
                "original_code": example["original_code"],
                "target_code": example.get("target_refactored", "")
            })
        
        return Dataset.from_list(formatted_examples)
    
    def train(self, dataset: Dataset, num_epochs: int = 3):
        """Train the model using PPO"""
        
        # Initialize PPO trainer
        ppo_trainer = PPOTrainer(
            config=self.ppo_config,
            model=self.model,
            tokenizer=self.tokenizer,
            dataset=dataset,
        )
        
        generation_kwargs = {
            "min_length": -1,
            "top_k": 0.0,
            "top_p": 1.0,
            "do_sample": True,
            "pad_token_id": self.tokenizer.eos_token_id,
            "max_new_tokens": 512,
        }
        
        reward_calculator = CodeQualityReward()
        
        for epoch in range(num_epochs):
            print(f"\n{'='*60}")
            print(f"Epoch {epoch + 1}/{num_epochs}")
            print(f"{'='*60}")
            
            epoch_rewards = []
            
            for batch_idx, batch in enumerate(tqdm(ppo_trainer.dataloader, desc=f"Epoch {epoch+1}")):
                query_tensors = batch["input_ids"]
                
                # Generate responses
                response_tensors = []
                for query in query_tensors:
                    response = ppo_trainer.generate(query, **generation_kwargs)
                    response_tensors.append(response.squeeze())
                
                # Decode responses
                batch_responses = [
                    self.tokenizer.decode(r.squeeze(), skip_special_tokens=True) 
                    for r in response_tensors
                ]
                
                # Calculate rewards
                rewards = []
                for i, response in enumerate(batch_responses):
                    original_code = dataset[batch_idx * self.ppo_config.batch_size + i]["original_code"]
                    
                    reward = reward_calculator.compute_reward(
                        original_code,
                        response
                    )
                    
                    rewards.append(torch.tensor(reward))
                    epoch_rewards.append(reward)
                
                # PPO update step
                stats = ppo_trainer.step(query_tensors, response_tensors, rewards)
                
                # Log statistics
                if batch_idx % 10 == 0:
                    print(f"\nBatch {batch_idx}:")
                    print(f"  Mean reward: {sum(epoch_rewards[-len(rewards):]) / len(rewards):.4f}")
                    print(f"  PPO loss: {stats.get('ppo/loss/total', 0):.4f}")
                    
                    if self.use_wandb:
                        wandb.log({
                            "batch": batch_idx,
                            "epoch": epoch,
                            "mean_reward": sum(epoch_rewards[-len(rewards):]) / len(rewards),
                            "ppo_loss": stats.get('ppo/loss/total', 0),
                        })
            
            # Epoch summary
            avg_epoch_reward = sum(epoch_rewards) / len(epoch_rewards) if epoch_rewards else 0
            print(f"\nEpoch {epoch + 1} Summary:")
            print(f"  Average reward: {avg_epoch_reward:.4f}")
            print(f"  Total batches: {batch_idx + 1}")
            
            if self.use_wandb:
                wandb.log({
                    "epoch": epoch,
                    "epoch_avg_reward": avg_epoch_reward,
                })
        
        return ppo_trainer
    
    def save_model(self, output_dir: str):
        """Save the trained model"""
        print(f"Saving model to {output_dir}")
        self.model.save_pretrained(output_dir)
        self.tokenizer.save_pretrained(output_dir)
        print("Model saved successfully!")


def load_training_data(filepath: str) -> List[Dict]:
    """Load training data from JSON file"""
    with open(filepath, 'r') as f:
        data = json.load(f)
    return data


def create_sample_dataset() -> List[Dict]:
    """Create a sample training dataset"""
    return [
        {
            "original_code": """
def calculate_sum(numbers):
    total = 0
    for i in range(len(numbers)):
        total = total + numbers[i]
    return total
""",
            "target_refactored": """
def calculate_sum(numbers):
    return sum(numbers)
"""
        },
        {
            "original_code": """
def find_max(lst):
    max_val = lst[0]
    for i in range(1, len(lst)):
        if lst[i] > max_val:
            max_val = lst[i]
    return max_val
""",
            "target_refactored": """
def find_max(lst):
    return max(lst)
"""
        },
        {
            "original_code": """
def is_even(n):
    if n % 2 == 0:
        return True
    else:
        return False
""",
            "target_refactored": """
def is_even(n):
    return n % 2 == 0
"""
        },
        {
            "original_code": """
def filter_positive(numbers):
    result = []
    for num in numbers:
        if num > 0:
            result.append(num)
    return result
""",
            "target_refactored": """
def filter_positive(numbers):
    return [num for num in numbers if num > 0]
"""
        },
        {
            "original_code": """
def count_vowels(text):
    vowels = ['a', 'e', 'i', 'o', 'u']
    count = 0
    for char in text.lower():
        if char in vowels:
            count = count + 1
    return count
""",
            "target_refactored": """
def count_vowels(text):
    vowels = set('aeiou')
    return sum(1 for char in text.lower() if char in vowels)
"""
        },
    ]


def main():
    parser = argparse.ArgumentParser(description="Train code refactoring model with PPO")
    parser.add_argument("--model", type=str, default="Salesforce/codet5p-770m",
                       help="Model name or path")
    parser.add_argument("--data", type=str, default=None,
                       help="Path to training data JSON file")
    parser.add_argument("--epochs", type=int, default=3,
                       help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=4,
                       help="Batch size for training")
    parser.add_argument("--learning-rate", type=float, default=1e-5,
                       help="Learning rate")
    parser.add_argument("--output-dir", type=str, default="./trained_model",
                       help="Output directory for trained model")
    parser.add_argument("--wandb", action="store_true",
                       help="Use Weights & Biases for logging")
    parser.add_argument("--sample-data", action="store_true",
                       help="Use sample dataset (for testing)")
    
    args = parser.parse_args()
    
    # Load training data
    if args.sample_data:
        print("Using sample training data")
        training_data = create_sample_dataset()
    elif args.data:
        print(f"Loading training data from {args.data}")
        training_data = load_training_data(args.data)
    else:
        print("Error: Must provide --data or use --sample-data")
        return
    
    print(f"Training examples: {len(training_data)}")
    
    # Initialize trainer
    trainer = RefactoringPPOTrainer(
        model_name=args.model,
        learning_rate=args.learning_rate,
        batch_size=args.batch_size,
        use_wandb=args.wandb
    )
    
    # Prepare dataset
    dataset = trainer.prepare_dataset(training_data)
    
    # Train
    print("\nStarting PPO training...")
    trained_model = trainer.train(dataset, num_epochs=args.epochs)
    
    # Save model
    trainer.save_model(args.output_dir)
    
    print("\n" + "="*60)
    print("Training complete!")
    print(f"Model saved to: {args.output_dir}")
    print("="*60)


if __name__ == "__main__":
    main()
