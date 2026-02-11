"""CLI entrypoint for the policy extraction pipeline."""
import argparse
from src import pipeline
from src.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run policy extraction pipeline")
    parser.add_argument("input_path", help="Path to input document or directory")
    parser.add_argument("--out", dest="out_dir", default="out", help="Output directory for JSON artifacts")
    parser.add_argument("--tenant", dest="tenant_id", default="tenant_default", help="Tenant identifier")
    parser.add_argument("--batch", dest="batch_id", default="batch_default", help="Batch identifier")
    parser.add_argument("--config", dest="config_path", default="configs/config.example.yaml", help="Path to YAML config")
    parser.add_argument("--stage5-input", dest="stage5_input", default=None, help="Path to Stage 5 runtime JSON(s) to ingest")
    args = parser.parse_args()

    config = load_config(args.config_path)

    # Wire up logging here; pipeline stub raises until implemented.
    pipeline.run_pipeline(
        input_path=args.input_path,
        output_dir=args.out_dir,
        tenant_id=args.tenant_id,
        batch_id=args.batch_id,
        config=config,
        stage5_input=args.stage5_input,
    )


if __name__ == "__main__":
    main()
