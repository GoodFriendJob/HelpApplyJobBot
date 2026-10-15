import time

import config
import utils


def main() -> None:
    start = time.time()
    if config.runDice:
        from dice import Dice
        Dice().start()
    if config.runZipRecruiter:
        from ziprecruiter import ZipRecruiter
        ZipRecruiter().start()
    runWellfound = getattr(config, "runWellfound", False)
    if runWellfound:
        from wellfound import Wellfound
        Wellfound().start()
    if not config.runDice and not config.runZipRecruiter and not runWellfound:
        utils.prRed("❌ Enable runDice, runZipRecruiter, or runWellfound in config.py.")
    utils.prYellow("---Took: " + str(round((time.time() - start) / 60)) + " minute(s).")


if __name__ == "__main__":
    main()
