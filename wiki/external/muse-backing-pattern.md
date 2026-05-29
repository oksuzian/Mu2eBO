# muse-backing-pattern — build a patched Offline subset against a Musing

**Type:** external
**Status:** active
**Updated:** 2026-05-26

## Summary

How to rebuild one or more Offline `.so` libraries with local patches while
inheriting everything else from a published Musing on CVMFS. Used to ship the
helical-plug `libmu2e_Mu2eG4.so` patch via `Code.tar.bz2` without needing
mmackenz's tree or new CVMFS publication.

## Canonical recipe (mgit + muse tarball)

This is the wiki-blessed path. Use it instead of the rsync-everything variant
below.

```bash
# 1. Pick a build root.
mkdir -p $WORK/autoresearch_muse && cd $WORK/autoresearch_muse
source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh

# 2. Backing chain. Separator is a SPACE; "SimJob/Run1Bak" is a parse error.
muse backing SimJob Run1Bak

# 3. Partial checkout. mgit init makes an empty sparse repo on
#    `mgit_init_branch`; mgit add <pkg> adds <pkg>/ to sparse-checkout.
mgit init
mgit add Mu2eG4

# 4. *** mgit add pulls HEAD of github.com/Mu2e/Offline main, NOT the backing's
#    tag.*** That breaks ABI against the rest of the backed libs. Overlay the
#    backing's tag onto the sparse tree:
( cd Offline && git checkout v13_12_10 -- Mu2eG4/ )

# 5. Apply local patch(es).
patch -p1 -d Offline < /path/to/helical-plug.patch

# 6. Enter Muse env. CRITICAL: do not pipe (subshell discards MUSE_*).
#    Let muse setup derive the qualifier from the backing chain — that's
#    the mu2ewiki-documented convention. Only pass `-q p094` explicitly
#    if the local `.muse` advertises a newer envset than the backing was
#    built against (see Key facts below).
muse setup >/tmp/setup.log 2>&1
echo $MUSE_WORK_DIR                            # expect: this dir

# 7. Build. -j 8 finishes in ~10-15 min on mu2egpvm.
muse build -j 8 >/tmp/build.log 2>&1

# 8. The rebuilt lib lives at:
ls build/al9-prof-e29-p094/Offline/lib/libmu2e_Mu2eG4.so

# 9. Package for grid (canonical — produces Code.tar.bz2 with a proper
#    setup.sh whose link order naturally prefers our libs over CVMFS).
muse tarball
# Output path printed to stdout: /mu2e/data/users/$USER/museTarball/tmp.<rand>/Code.tar.bz2
```

## Legacy recipe (rsync; do not use for new work)

Worked but ships the *entire* Offline source via rsync rather than a sparse
checkout. Kept for reference because the Offline_helical/ tree built this way
still exists on disk.

```bash
mkdir -p $WORK/Offline_helical && cd $WORK/Offline_helical
rsync -a /cvmfs/mu2e.opensciencegrid.org/Musings/Offline/v13_12_10/Offline/ Offline/
patch -p1 -d Offline < helical-plug.patch
muse backing SimJob Run1Bak
muse setup >/tmp/setup.log 2>&1
muse build -j 8 >/tmp/build.log 2>&1
```

## Key facts

- **Backing chain syntax:** `muse backing SimJob Run1Bak` (space-separated).
  `SimJob/Run1Bak` is a parse error.
- **Backing transitivity:** our local build → `SimJob/Run1Bak` →
  `Offline/v13_12_10`. Verbose `muse -v setup` confirms this: it adds
  `/cvmfs/.../SimJob/Run1Bak` AND `/cvmfs/.../Offline/v13_12_10` to the
  search/build paths. The rebuilt lib's rpath includes the v13_12_10 lib dir,
  so ABI compatibility is guaranteed by construction.
- **`MUSE_WORK_DIR` does NOT propagate through pipes.** `muse setup -q p094 |
  tail -3` leaves the variable unset in the calling shell — the env was set
  inside the pipe's subshell and discarded. Redirect to a file (`>...log
  2>&1`) and read it after.
- **Envset must match Run1Bak's:** `p094` is what Run1Bak built against; using
  a different qualifier produces a lib the workers can't dlopen cleanly.
- **`muse setup` derives the qualifier from the backing chain.** In the
  `autoresearch_muse/` rsync layout used today, plain `muse setup` (no `-q`)
  picks `p094` correctly because the top-level `.muse` came from
  `Musings/Offline/v13_12_10`. This matches the mu2ewiki-documented
  workflow — no explicit `-q` needed.
- **`-q p094` override is only needed in the mgit-add scenario.** Tested
  2026-05-17 with `mgit init` + `mgit add Mu2eG4`: `muse setup` with no
  `-q` picked `p095` because `mgit add` pulled main HEAD whose top-level
  `.muse` advertises a newer envset than the backing. Result: `ERROR -
  backing build area missing required build (al9-prof-e29-p095)`. The
  `git checkout v13_12_10 -- Mu2eG4/` overlay covers only the added subdir;
  top-level `.muse` is still from main. In *that* layout only, pass
  `-q p094` to override. The rsync recipe doesn't hit this because it
  overlays the whole v13_12_10 tree including the top-level `.muse`.
- **Full Offline source is required.** A partial overlay
  (`.muse` + one `.cc`) makes `scons` say "up to date" and produces nothing —
  the SConscript chain needs the whole tree.
- **Incremental rebuild gotcha (2026-05-20).** After editing one `.cc`,
  `muse build Offline` reports "up to date" without relinking the changed lib
  (the package-level target stops short). Targeting the .so explicitly works:
  ```bash
  muse build build/al9-prof-e29-p094/Offline/lib/libmu2e_Mu2eG4.so
  ```
  This recompiles the changed .os and relinks the .so. Also: `muse build
  Offline/Mu2eG4/src/foo.os` errors with "Do not know how to make File
  target" — scons names objects under `build/.../tmp/Mu2eG4/src/foo.os`, not
  the package subdir; the lib-level target is the safe granularity.
- **Patch isolation:** `git diff Mu2eG4/src/constructTSdA.cc` in mmackenz's
  checkout extracted the +112-line helical-plug change cleanly, separating it
  from his 10 other unrelated working-tree mods.
- **Run1Bak's `constructTSdA.cc` matches mmackenz's `Run1BTargetDesigns`
  branch HEAD exactly** — Run1Bak was built from his fork, not from
  `Mu2e/Offline` main.

## Cross-links

- Used by: [[pipeline]] (`write_code_tarball` ships `Code/lib/libmu2e_Mu2eG4.so`
  + `LD_PRELOAD` in `setup.sh`)
- Motivating bug: [[calo-constant-across-helical]]
- Project: [[bo-helical]]
- Source patch: `/exp/mu2e/app/users/oksuzian/Offline_helical/helical-plug.patch`
- Build dir: `/exp/mu2e/app/users/oksuzian/Offline_helical/build/al9-prof-e29-p094/Offline/lib/`
- Mu2e wiki: https://mu2ewiki.fnal.gov/wiki/GitHubWorkflow#Developer_Workflow

## Out-of-scope: Run1BAna (EdepAna)

The harvest step calls a `mu2e` job that loads `EdepAna_module`, which lives
in mmackenz's personal `Run1BAna` repo (`github.com/michaelmackenzie/Run1BAna`,
**not** in the Mu2e org, **not** in Offline, **not** in Run1Bak). Building it
under the same `autoresearch_muse/` tree was attempted 2026-05-17 and failed:

- `Run1BAna/evtana/inc/Run1BEvtAna.hh` includes `EventNtuple/inc/HitCount.hh`
  — that repo isn't checked out.
- `Run1BAna/modules/src/CalLineFinder_module.cc:421` references
  `mu2e::CosmicTrackSeed::_caloCluster`, a member that exists in Run1BAna HEAD
  but **not** in `v13_12_10`'s `CosmicTrackSeed`. Run1BAna HEAD's ABI has
  drifted past the backing.

Since the harvest is local-only (not a grid step), the cheap fix is to
prepend mmackenz's prebuilt lib dir
(`/exp/mu2e/app/users/mmackenz/run1b/build/al9-prof-e29-p094/Run1BAna/lib`)
to `CET_PLUGIN_PATH` + `LD_LIBRARY_PATH` in `pipeline.py:sourced_env(with_muse=True)`.
The mmackenz lib was built against the same `Run1Bak` / v13_12_10 backing
with the same envset, so ABI matches by construction.

To rebuild Run1BAna locally we would need: (a) check out an older Run1BAna
tag whose ABI matches `v13_12_10`, (b) also check out `EventNtuple`, (c)
muse build. Not worth doing unless the borrow path stops working.

## Open questions / TODO

- If we add more patches that touch headers, may need to rebuild more than
  just `libmu2e_Mu2eG4.so`. Watch link-time errors on dependents.
