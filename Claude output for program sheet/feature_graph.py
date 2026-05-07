import importlib.util, sys
from pathlib import Path
_p = Path(__file__).parent / "2a. feature_graph.py"
_spec = importlib.util.spec_from_file_location("_feature_graph_impl", _p)
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)
sys.modules[__name__].__dict__.update({k: v for k, v in _m.__dict__.items() if not k.startswith('__')})
