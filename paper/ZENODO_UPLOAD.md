**Version 1 is published:** https://doi.org/10.5281/zenodo.23582871 (record 23582871; all versions 10.5281/zenodo.23582870). For a new version, open the record on Zenodo and choose *New version* - the steps below still apply.

# Publishing the paper on Zenodo (about three minutes, done by you)

1. Put your name in three places: `paper/neo4d.tex` (`\author{[Author name]...}`), `paper/zenodo_metadata.json`
   (`creators`) and `CITATION.cff`. Rebuild the PDF: `cd paper && tectonic neo4d.tex`.
2. The code is public at https://github.com/devkancheti4-design/neo4d; you may also attach `neo4d-source.zip`
   (made by `git archive`, see below) so the record holds the exact version.
3. Go to https://zenodo.org, log in, and choose **New upload**.
4. Files: `paper/neo4d.pdf` (and, if you choose, `neo4d-source.zip`).
5. Fill the form from `paper/zenodo_metadata.json`: Resource type *Publication / Preprint*, the title, your name,
   the description (the abstract), keywords, licence CC BY 4.0.
6. **Publish.** Zenodo gives the record a DOI. A published record cannot be deleted - only new versions added - so read
   the PDF once more first.

Making the source archive (from the repository root):

    git archive --format=zip -o ../neo4d-source.zip HEAD

Alternative: connect GitHub to Zenodo (Zenodo > Settings > GitHub), switch the repository on, and publish a GitHub
release; Zenodo archives each release with a DOI automatically, reading `.zenodo.json` and `CITATION.cff`.
