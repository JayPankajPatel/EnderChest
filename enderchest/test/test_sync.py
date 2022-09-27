"""Test functionality around rsync script generation"""
import os
import shutil
import subprocess
import sys

import pytest

from enderchest import sync
from enderchest.craft import craft_ender_chest
from enderchest.place import place_enderchest
from enderchest.sync import Remote

remotes = (
    Remote("localhost", "~/minecraft", "openbagtwo", "Not Actually Remote"),
    Remote("8.8.8.8", "/root/minecraft", "sergey", "Not-Bing"),
    Remote("spare-pi", "/opt/minecraft", "pi"),
    Remote("steamdeck.local", "~/minecraft"),
)


class TestRemote:
    @pytest.mark.parametrize("remote", remotes)
    def test_remote_is_trivially_serializable(self, remote):
        remote_as_str = str(remote)
        remote_from_str = eval(remote_as_str)  # not that you should ever use eval

        assert remote == remote_from_str

    @pytest.mark.parametrize(
        "remote, expected",
        zip(
            remotes, ("Not Actually Remote", "Not-Bing", "spare-pi", "steamdeck.local")
        ),
    )
    def test_alias_fallback(self, remote, expected):
        assert remote.alias == expected

    @pytest.mark.parametrize(
        "remote, expected",
        zip(
            remotes,
            (
                "openbagtwo@localhost:~/minecraft",
                "sergey@8.8.8.8:/root/minecraft",
                "pi@spare-pi:/opt/minecraft",
                "steamdeck.local:~/minecraft",
            ),
        ),
    )
    def test_remote_folder(self, remote, expected):
        assert remote.remote_folder == expected


class TestScriptGeneration:
    @pytest.mark.parametrize("script", ("open.sh", "close.sh"))
    def test_link_to_other_chests_generates_executable_scripts(
        self, script, local_enderchest
    ):
        assert list((local_enderchest / "local-only").glob("*.sh")) == []

        sync.link_to_other_chests(local_enderchest / "..", *remotes)

        assert os.access(local_enderchest / "local-only" / script, os.X_OK)

    @pytest.mark.parametrize("script", ("open.sh", "close.sh"))
    def test_link_by_default_does_not_overwrite_scripts(self, script, local_enderchest):
        (local_enderchest / "local-only" / script).write_text("echo hello\n")

        with pytest.warns() as warning_log:
            sync.link_to_other_chests(local_enderchest / "..", *remotes)

        assert len(warning_log) == 1
        assert "skipping" in warning_log[0].message.args[0].lower()

        assert (local_enderchest / "local-only" / script).read_text() == "echo hello\n"

    def test_link_can_be_made_to_overwrite_scripts(self, local_enderchest):
        for script in ("open.sh", "close.sh"):
            (local_enderchest / "local-only" / script).write_text("echo hello\n")

        with pytest.warns() as warning_log:
            sync.link_to_other_chests(local_enderchest / "..", *remotes, overwrite=True)

        assert len(warning_log) == 2
        assert all(
            (
                "overwriting" in warning_message.message.args[0].lower()
                for warning_message in warning_log
            )
        )

        assert not any(
            (
                (local_enderchest / "local-only" / script).read_text() == "echo hello\n"
                for script in ("open.sh", "close.sh")
            )
        )

    @pytest.mark.parametrize("script", ("open.sh", "close.sh"))
    @pytest.mark.xfail(sys.platform.startswith("win"), reason="only done bash so far")
    def test_scripts_just_scare_and_quit_by_default(self, script, local_enderchest):
        sync.link_to_other_chests(
            local_enderchest / ".."
        )  # no remotes means shouldn't do anything even if test fails

        script_path = local_enderchest / "local-only" / script
        with script_path.open("a") as script_file:
            script_file.write('echo "I should not be reachable"\n')

        result = subprocess.run(
            [script_path, "--dry-run"],  # out of an overabundance of caution
            capture_output=True,
        )

        assert result.returncode == 1
        assert "DELETE AFTER READING" in result.stdout.decode()
        if script == "open.sh":
            assert "Could not pull changes" not in result.stdout.decode()
        assert "I should not be reachable" not in result.stdout.decode()

    @pytest.mark.parametrize("script", ("open.sh", "close.sh"))
    @pytest.mark.xfail(sys.platform.startswith("win"), reason="only done bash so far")
    def test_yes_you_can_disable_the_scare_warning(self, script, local_enderchest):
        sync.link_to_other_chests(local_enderchest / "..", omit_scare_message=True)

        script_path = local_enderchest / "local-only" / script
        with script_path.open("a") as script_file:
            script_file.write('echo "You made it"\n')

        result = subprocess.run(
            [script_path, "--dry-run"],  # out of an overabundance of caution
            capture_output=True,
        )

        if script == "open.sh":
            assert result.returncode == 1
            assert "Could not pull changes" in result.stdout.decode()
        else:
            assert result.returncode == 0
            assert "You made it" in result.stdout.decode()


@pytest.mark.xfail(sys.platform.startswith("win"), reason="only done bash so far")
class TestSyncing:
    """This is only going to cover syncing locally"""

    # TODO: add tests for rsync over ssh

    @pytest.fixture
    def remote(self, tmp_path, local_enderchest):
        another_root = tmp_path / "not-so-remote"
        craft_ender_chest(another_root)

        ender_chest = another_root / "EnderChest"

        shutil.copy(
            (local_enderchest / "client-only" / "resourcepacks" / "stuff.zip@axolotl"),
            (ender_chest / "client-only" / "resourcepacks" / "stuff.zip@axolotl"),
            follow_symlinks=False,
        )

        shutil.copy(
            (local_enderchest / "client-only" / "saves" / "olam@axolotl@bee@cow"),
            (ender_chest / "client-only" / "saves" / "olam@axolotl@bee@cow"),
            follow_symlinks=False,
        )

        for instance in ("axolotl", "bee", "cow"):
            shutil.copy(
                (local_enderchest / "global" / "mods" / f"BME.jar@{instance}"),
                (ender_chest / "global" / "mods" / f"BME.jar@{instance}"),
                follow_symlinks=False,
            )

        (another_root / "AnOkayMod.jar").write_bytes(b"beep")
        (ender_chest / "global" / "mods" / "AnOkayMod.jar@bee").symlink_to(
            (another_root / "AnOkayMod.jar")
        )

        (
            ender_chest
            / "local-only"
            / "shaderpacks"
            / "SildursMonochromeShaders.zip@axolotl@bee@cow@dolphin"
        ).touch()
        (ender_chest / "local-only" / "BME_indev.jar@axolotl").write_bytes(
            b"alltheboops"
        )
        (
            ender_chest / "client-only" / "config" / "pupil.properties@axolotl@bee@cow"
        ).write_text("dilated\n")

        yield Remote(None, ender_chest / "..", None, "behind_the_door")

        assert list(ender_chest.glob(".git")) == []
        assert (another_root / "AnOkayMod.jar").read_bytes() == b"beep"

    def test_open_grabs_changes_from_upstream(self, local_enderchest, remote):
        (local_enderchest / ".." / "instances" / "bee" / ".minecraft").mkdir(
            parents=True
        )

        sync.link_to_other_chests(
            local_enderchest / "..", remote, omit_scare_message=True
        )

        result = subprocess.run(
            [local_enderchest / "local-only" / "open.sh", "--verbose"],
            capture_output=True,
        )

        assert result.returncode == 0

        place_enderchest(local_enderchest / "..")

        assert sorted(
            (
                path.name
                for path in (
                    local_enderchest
                    / ".."
                    / "instances"
                    / "bee"
                    / ".minecraft"
                    / "mods"
                ).glob("*")
            )
        ) == ["AnOkayMod.jar", "BME.jar"]

    def test_open_processes_deletions_from_upstream(self, local_enderchest, remote):
        (local_enderchest / ".." / "instances" / "bee" / ".minecraft").mkdir(
            parents=True
        )

        sync.link_to_other_chests(
            local_enderchest / "..", remote, omit_scare_message=True
        )

        result = subprocess.run(
            [local_enderchest / "local-only" / "open.sh", "--verbose"],
            capture_output=True,
        )

        assert result.returncode == 0

        place_enderchest(local_enderchest / "..")

        assert (
            list(
                (
                    local_enderchest
                    / ".."
                    / "instances"
                    / "bee"
                    / ".minecraft"
                    / "resourcepacks"
                ).glob("*")
            )
            == []
        )

    def test_close_overwrites_with_changes_from_local(self, local_enderchest, remote):
        (
            local_enderchest
            / "client-only"
            / "config"
            / "pupil.properties@axolotl@bee@cow"
        ).write_text("constricted\n")

        remote_config = (
            remote.root
            / "EnderChest"
            / "client-only"
            / "config"
            / "pupil.properties@axolotl@bee@cow"
        )
        assert remote_config.read_text() == "dilated\n"

        sync.link_to_other_chests(
            local_enderchest / "..", remote, omit_scare_message=True
        )

        result = subprocess.run(
            [local_enderchest / "local-only" / "close.sh", "--verbose"],
            capture_output=True,
        )

        assert result.returncode == 0

        assert remote_config.read_text() == "constricted\n"

    def test_close_deletes_remote_copies_when_locals_are_deleted(
        self, local_enderchest, remote
    ):
        file_to_be_removed = (
            remote.root
            / "EnderChest"
            / "client-only"
            / "config"
            / "pupil.properties@axolotl@bee@cow"
        )
        link_to_be_removed = (
            remote.root / "EnderChest" / "global" / "mods" / "AnOkayMod.jar@bee"
        )

        for object_to_be_removed in (file_to_be_removed, link_to_be_removed):
            assert list(
                object_to_be_removed.parent.glob(object_to_be_removed.name)
            ) == [object_to_be_removed]

        sync.link_to_other_chests(
            local_enderchest / "..", remote, omit_scare_message=True
        )

        result = subprocess.run(
            [local_enderchest / "local-only" / "close.sh", "--verbose"],
            capture_output=True,
        )

        assert result.returncode == 0

        for object_to_be_removed in (file_to_be_removed, link_to_be_removed):
            assert (
                list(object_to_be_removed.parent.glob(object_to_be_removed.name)) == []
            )
