from mooBird import MooBird
import yaml

if __name__ == '__main__':
    with open('config.yaml') as cfg_file:
        cfg_data = yaml.safe_load(cfg_file)

    mooBird = MooBird(cfg_data)
    mooBird.exec()
