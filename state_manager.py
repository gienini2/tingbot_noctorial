import json

class StateManager:
    def __init__(self, filepath='state.json'):
        self.filepath = filepath
        self.state = self.load_state()

    def load_state(self):
        try:
            with open(self.filepath, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {'positions': {}, 'metrics': {}}

    def save_state(self):
        with open(self.filepath, 'w') as f:
            json.dump(self.state, f, indent=4)

    def update_position(self, symbol, quantity, price):
        self.state['positions'][symbol] = {'quantity': quantity, 'price': price}
        self.save_state()

    def update_metric(self, metric_name, value):
        self.state['metrics'][metric_name] = value
        self.save_state()

    def get_position(self, symbol):
        return self.state['positions'].get(symbol)

    def get_metric(self, metric_name):
        return self.state['metrics'].get(metric_name)