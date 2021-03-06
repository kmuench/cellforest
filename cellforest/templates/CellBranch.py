import os
from copy import deepcopy
from pathlib import Path
from typing import Optional, Union, List, Tuple

from dataforest.core.DataBranch import DataBranch
from dataforest.core.Spec import Spec
from dataforest.utils.utils import label_df_partitions
import pandas as pd

from cellforest.structures.counts.Counts import Counts
from cellforest.templates.ReaderMethodsSC import ReaderMethodsSC
from cellforest.templates.WriterMethodsSC import WriterMethodsSC
from cellforest.utils.cellranger.DataMerge import DataMerge


class CellBranch(DataBranch):
    """
    DataBranch for scRNAseq processed data. The `process_hierarchy` currently
    starts at `combine`, where non-normalized counts data is combined.

    A path through specific `process_runs` of processes in the
    `process_hierarchy` are specified in the `spec`, according to the
    specifications of `dataforest.Spec`. Any root level (not under a process
    name in `spec`) `subset`s or `filter`s are applied to `counts` and
    `meta`, which are the preferred methods for accessing cell metadata and
    the normalized counts matrix
    """

    READER_METHODS = ReaderMethodsSC
    WRITER_METHODS = WriterMethodsSC
    DATA_FILE_ALIASES = {"rna", "vdj", "surface", "antigen", "cnv", "atac", "spatial", "crispr"}
    READER_KWARGS_MAP = {
        "reduce": {
            "pca_embeddings": {"header": "infer"},
            "pca_loadings": {"header": "infer"},
            "umap_embeddings": {"header": "infer", "index_col": 0},
        },
        "combine": {"cell_metadata": {"header": 0}},
        "cluster": {"clusters": {"index_col": 0}},
        "diffexp": {"diffexp_result": {"header": 0}},
    }
    _METADATA_NAME = "meta"
    _COPY_KWARGS = {**DataBranch._COPY_KWARGS, "unversioned": "unversioned"}
    _ASSAY_OPTIONS = ["rna", "vdj", "surface", "antigen", "cnv", "atac", "spatial", "crispr"]
    _DEFAULT_CONFIG = Path(__file__).parent.parent / "config/default_config.yaml"

    def __init__(
        self,
        root_dir: Union[str, Path],
        spec: Optional[Union[list, Spec]] = None,
        verbose: bool = False,
        # meta: Optional[pd.DataFrame] = None,
        config: Optional[Union[str, Path, dict]] = None,
        unversioned: Optional[bool] = None,
    ):
        super().__init__(root_dir, spec, verbose, config)
        self.assays = set()
        self._rna = None
        # self._meta_unfiltered = None
        # if meta is not None:
        #     meta = meta.copy()
        # self._meta = self._get_cell_meta(meta)
        self._meta = None
        # TODO: use this to augment strings of output directories so manual tinkers don't
        #   affect downstream processing
        # if meta is not None and unversioned is None:
        #     self._unversioned = True
        # else:
        #     self._unversioned = bool(unversioned)
        # if self.unversioned:
        #     self.logger.warning(f"Unversioned DataBranch")

    @property
    def samples(self) -> pd.DataFrame:
        """
        Hierarchical categorization of all samples in dataset with cell counts.
        The canonical use case would be to use it on a broad DataBranch to choose
        a dataset.
        Returns:

        """
        raise NotImplementedError()

    @property
    def meta(self) -> pd.DataFrame:
        """
        Interface for cell metadata, which is derived from the sample
        metadata and the scrnaseq experimental data. Available UMAP embeddings
        and cluster identifiers will be included, and the data will be subset,
        filtered, and partitioned based on the specifications in `self.spec`.
        Primarily for this reason, this is the preferred interface to metadata
        over direct file access.
        """
        # TODO: add embeddings and cluster ids
        if self._meta is None:
            self._meta = self._get_cell_meta(self.current_process)
        return self._meta

    @property
    def rna(self) -> Counts:
        """
        Interface for normalized counts data. It uses the `Counts` wrapper
        around `scipy.sparse.csr_matrix`, which allows for slicing with
        `cell_id`s and `gene_name`s.
        """
        if self._rna is None or not self._rna.index.equals(self.meta.index):
            if self.current_process is not None:
                path_map = self[self.current_process].path_map
                counts_path = path_map["rna"]
            else:
                # TODO: fix hardcoding
                counts_path = self.root_dir / "rna.pickle"
            if not counts_path.exists():
                raise FileNotFoundError(
                    f"Ensure that you initialized the root directory with CellBranch.from_metadata or "
                    f"CellBranch.from_input_dirs. Not found: {counts_path}"
                )
            self._rna = Counts.load(counts_path)
        if not self._rna.index.equals(self.meta.index):
            self._rna = self._rna[self.meta.index]
        return self._rna

    @property
    def vdj(self):
        raise NotImplementedError()

    @property
    def surface(self):
        raise NotImplementedError()

    @property
    def antigen(self):
        raise NotImplementedError()

    @property
    def cnv(self):
        raise NotImplementedError()

    @property
    def atac(self):
        raise NotImplementedError()

    @property
    def spatial(self):
        raise NotImplementedError()

    @property
    def crispr(self):
        raise NotImplementedError()

    def groupby(self, by: Union[str, list, set, tuple], **kwargs) -> Tuple[str, "CellBranch"]:
        """
        Operates like a pandas groupby, but does not return a GroupBy object,
        and yields (name, DataBranch), where each DataBranch is subset according to `by`,
        which corresponds to columns of `self.meta`.
        This is useful for batching analysis across various conditions, where
        each run requires an DataBranch.
        Args:
            by: variables over which to group (like pandas)
            **kwargs: for pandas groupby on `self.meta`

        Yields:
            name: values for DataBranch `subset` according to keys specified in `by`
            branch: new DataBranch which inherits `self.spec` with additional `subset`s
                from `by`
        """
        raise NotImplementedError("currently not functioning")
        if isinstance(by, (tuple, set)):
            by = list(by)
        for (name, df) in self.meta.groupby(by, **kwargs):
            if isinstance(by, list):
                if isinstance(name, (list, tuple)):
                    subset_dict = dict(zip(by, name))
                else:
                    subset_dict = {by[0]: name}
            else:
                subset_dict = {by: name}
            forest = self.get_subset(subset_dict)
            # branch._meta = df
            yield name, forest

    @property
    def unversioned(self) -> bool:
        return self._unversioned

    def copy(self, reset: bool = False, **kwargs) -> "CellBranch":
        if kwargs.get("meta", None) is not None:
            kwargs["unversioned"] = True
        if not kwargs:
            kwargs["meta"] = self._meta  # save compute if no modifications
        base_kwargs = self._get_copy_base_kwargs()
        kwargs = {**base_kwargs, **kwargs}
        kwargs = {k: deepcopy(v) for k, v in kwargs.items()}
        if reset:
            kwargs = base_kwargs
        return self.__class__(**kwargs)

    def set_partition(self, process_name: Optional[str] = None, encodings=True):
        """Add columns to metadata to indicate partition from spec"""
        columns = self.spec[process_name]["partition"]
        self._meta = label_df_partitions(self.meta, columns, encodings)

    def _get_cell_meta(self, process_name: str) -> pd.DataFrame:
        """
        Read in cell metadata and performs modifications:
            - replace any spaces with underscores
            - merge metadata from process precursors and current process
            - performs data operations (subset, filter, partition)
        Args:
            df: if provided, skip first two steps and go straight to data ops
        Returns:
            df: modified metadata dataframe
        """
        try:
            df = pd.read_csv(self["root"].path_map["meta"], sep="\t", index_col=0)
        except FileNotFoundError:
            df = pd.DataFrame(self.rna.cell_ids.copy())
            df.columns = ["cell_id"]
            df.index = df["cell_id"]
            df.drop(columns=["cell_id"], inplace=True)
        if process_name is not None:
            precursor_names = self.spec.get_precursors_lookup(incl_current=True)[process_name]
            for precursor_name in precursor_names:
                try:
                    process_meta = self[precursor_name].process_meta
                except FileNotFoundError:
                    pass
                else:
                    intersect_cols = set(df.columns).intersection(set(process_meta.columns))
                    process_meta.drop(intersect_cols, axis=1, inplace=True)
                    df = df.merge(process_meta, left_index=True, right_index=True)
        df.replace(" ", "_", regex=True, inplace=True)
        partitions_list = self.spec.get_partition_list(process_name)
        partitions = set().union(*partitions_list)
        if partitions:
            df = label_df_partitions(df, partitions, encodings=True)
        return df

    @staticmethod
    def _combine_datasets(
        root_dir: Union[str, Path],
        metadata: Optional[Union[str, Path, pd.DataFrame]] = None,
        input_paths: Optional[List[Union[str, Path]]] = None,
        metadata_read_kwargs: Optional[dict] = None,
        mode: Optional[str] = None,
    ):
        """
        Combine files from multiple cellranger output directories into a single
        `Counts` and save it to `root_dir`. If sample metadata is provided,
        replicate each row corresponding to the number of cells in the sample
        such that the number of rows changes from n_samples to n_cells.
        """
        root_dir = Path(root_dir)
        mode = mode if mode else "rna"
        if (input_paths and metadata) or (input_paths is None and metadata is None):
            raise ValueError("Must specify exactly one of `input_dirs` or `metadata`")
        elif metadata is not None:
            if isinstance(metadata, (str, Path)):
                metadata_read_kwargs = {"sep": "\t"} if not metadata_read_kwargs else metadata_read_kwargs
                metadata = pd.read_csv(metadata, **metadata_read_kwargs)
            prefix = "path_"
            assays = [x[len(prefix) :] for x in metadata.columns if x.startswith(prefix)]
            if len(assays) == 0:
                raise ValueError(
                    f"metadata must contain at least once column named with the prefix, `path_`, and one of the "
                    f"following assays as a suffix: {CellBranch._ASSAY_OPTIONS}"
                )
            for assay in assays:
                paths = metadata[f"{prefix}{assay}"].tolist()
                DataMerge.merge_assay(paths, assay, metadata, save_dir=root_dir)
        else:
            DataMerge.merge_assay(input_paths, mode, save_dir=root_dir)
        return dict()

    @staticmethod
    def _get_assays(path):
        # TODO: will have to change once decoupled from pickle (e.g. rds, anndata)
        files = list(filter(lambda x: x.endswith(".pickle"), os.listdir(path)))
        return set(map(lambda x: x.split(".")[0], files))
