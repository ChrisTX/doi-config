#!/usr/bin/env python3
import argparse
import pathlib
import shutil
import vdf
from typing import Any, List


class WorkshopCacheException(Exception):
    """Base class of all workshop cache exceptions."""


class WorkshopCacheEmpty(WorkshopCacheException):
    """Workshop cache is not initialised."""


class WorkshopCache:
    """Workshop cache for a given application."""

    def __init__(self, base_path: pathlib.Path) -> None:
        """Initialise the workshop cache for a path."""
        self._vdf = None

        if not base_path.is_dir() or not base_path.exists():
            raise WorkshopCacheException("specified path does not exist.")

        appid_path = base_path / 'steam_appid.txt'

        if appid_path.is_dir() or not appid_path.exists():
            raise WorkshopCacheException("steam_appid.txt does not exist.")

        with open(appid_path, 'r') as appid_file:
            self._appid = int(appid_file.readline().rstrip())

        if not isinstance(self._appid, int) or not (self._appid >= 1):
            raise ValueError("appid must be an integer larger 0.")

        self._cache_path = base_path / 'steamapps' / 'workshop'
        if not self._cache_path.is_dir() or not self._cache_path.exists():
            raise WorkshopCacheEmpty("Workshop cache folder does not exist.")

        self._content_path = self._cache_path / 'content' / str(self._appid)
        if not self._content_path.is_dir() or not self._content_path.exists():
            raise WorkshopCacheEmpty("Workshop content folder does not exist.")

        self._vdf_path = self._cache_path / f'appworkshop_{self._appid}.acf'
        if self._vdf_path.is_dir() or not self._vdf_path.exists():
            raise WorkshopCacheEmpty("Workshop ACF does not exist.")
        with open(self._vdf_path, 'r') as vdf_file:
            self._vdf = vdf.load(vdf_file, mapper=vdf.VDFDict)

    def __del__(self) -> None:
        """Write out the VDF on destruction."""
        if not self._vdf is None:
            self.write()

    def _get_main(self) -> Any:
        """Retrieve the main key of the VDF."""
        return self._vdf['AppWorkshop']

    def _adjust_size_on_disk(self, size_adjustment) -> None:
        """Adjust the on disk size of the VDF."""
        old_size = int(self._get_main()['SizeOnDisk'])
        self._get_main()[(0, 'SizeOnDisk')] = old_size + size_adjustment

    def remove_item(self, item_id: int) -> None:
        """Remove a single item_id from the workshop cache."""
        try:
            item_size = int(self._get_main()['WorkshopItemsInstalled'][str(
                item_id)]['size'])
        except KeyError:
            # Item isn't installed, so there's nothing to do
            return

        print(f"Workshop: removing {item_id} of size {item_size}")

        # We don't ignore any further KeyError exceptions now
        # If any occur, the VDF file is inconsistent
        self._adjust_size_on_disk(-item_size)
        self._get_main()['WorkshopItemsInstalled'].remove_all_for(str(item_id))
        self._get_main()['WorkshopItemDetails'].remove_all_for(str(item_id))

        item_path = self._content_path / str(item_id)
        if not item_path.is_dir() or not item_path.exists():
            raise WorkshopCacheException(
                "Workshop item exists in ACF but not on disk.")

        shutil.rmtree(item_path)

    def remove_items(self, item_ids: List[int]) -> None:
        """Remove a list of item_ids from the workshop cache."""
        for id in item_ids:
            self.remove_item(id)

    def write(self) -> None:
        """Write out the modified VDF file."""
        with open(self._vdf_path, 'w') as vdf_file:
            vdf.dump(self._vdf, vdf_file, pretty=True)


def parse_args() -> argparse.Namespace:
    """Set up the commandline arguments parser."""
    p = argparse.ArgumentParser(
        description=
        "Utility that allows removing individual workshop items from the cache."
    )

    p.add_argument("-i",
                   "--item",
                   nargs='+',
                   type=int,
                   help="Workshop items to delete",
                   required=True)
    p.add_argument("-p",
                   "--path",
                   type=pathlib.Path,
                   help="Path of the installed application (base folder)",
                   required=True)
    return p.parse_args()


def main() -> None:
    """Main function."""
    args = parse_args()

    wscache = WorkshopCache(args.path)
    wscache.remove_items(args.item)


if __name__ == "__main__":
    main()
