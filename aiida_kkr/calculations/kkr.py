# -*- coding: utf-8 -*-
"""
Input plug-in for a KKR calculation.
"""
import os
from numpy import array

from aiida.orm.calculation.job import JobCalculation
from aiida_kkr.calculations.voro import VoronoiCalculation
from aiida.common.utils import classproperty
from aiida.common.constants import elements as PeriodicTableElements
from aiida.common.exceptions import (InputValidationError, ValidationError, NotExistent)
from aiida.common.datastructures import (CalcInfo, CodeInfo)
from aiida.orm import DataFactory
from aiida.common.exceptions import UniquenessError
from aiida_kkr.tools.kkr_params import kkrparams
from aiida_kkr.tools.common_functions import get_alat_from_bravais, get_Ang2aBohr

#define aiida structures from DataFactory of aiida
RemoteData = DataFactory('remote')
ParameterData = DataFactory('parameter')
StructureData = DataFactory('structure')

#list of globally used constants
a_to_bohr = get_Ang2aBohr()

class KkrCalculation(JobCalculation):
    """
    AiiDA calculation plugin for a KKR calculation
    .
    """

    def _init_internal_params(self):
        """
        Init internal parameters at class load time
        """
        # reuse base class function
        super(KkrCalculation, self)._init_internal_params()
       
        # Default input and output files
        self._DEFAULT_INPUT_FILE = 'inputcard' # will be shown with inputcat
        self._DEFAULT_OUTPUT_FILE = 'out_kkr'  # verdi shell output will be shown with outputcat
        
        # same as _DEFAULT_OUTPUT_FILE: piped output of kkr execution to this file
        self._OUTPUT_FILE_NAME = 'out_kkr'

        # List of mandatory input files
        self._INPUT_FILE_NAME = 'inputcard'
        self._POTENTIAL = 'potential'

        # List of optional input files (may be mandatory for some settings in inputcard)
        self._SHAPEFUN = 'shapefun' # mandatory if nonspherical calculation
        self._SCOEF = 'scoef' # mandatory for KKRFLEX calculation
        self._NONCO_ANGLES = 'nonco_angles.dat' # mandatory if noncollinear directions are used that are not (theta, phi)= (0,0) for all atoms

	
	   # List of output files that should always be present
        self._OUT_POTENTIAL = 'out_potential'
        self._OUTPUT_0_INIT = 'output.0.txt'
        self._OUTPUT_000 = 'output.000.txt'
        self._OUT_TIMING_000 = 'out_timing.000.txt'
        self._NONCO_ANGLES_OUT = 'nonco_angles_out.dat'

        
        # template.product entry point defined in setup.json
        self._default_parser = 'kkr.kkrparser'
        
        # files that will be copied from local computer if parent was KKR calc
        self._copy_filelist_kkr = [self._SHAPEFUN, self._OUT_POTENTIAL]

        
    @classproperty
    def _use_methods(cls):
        """
        Add use_* methods for calculations.
        
        Code below enables the usage
        my_calculation.use_parameters(my_parameters)
        """
        use_dict = JobCalculation._use_methods
        use_dict.update({
            "parameters": {
                'valid_types': ParameterData,
                'additional_parameter': None,
                'linkname': 'parameters',
                'docstring':
                ("Use a node that specifies the input parameters ")
            },
            "parent_folder": {
                'valid_types': RemoteData,
                'additional_parameter': None,
                'linkname': 'parent_calc_folder',
                'docstring': (
                    "Use a remote or local repository folder as parent folder "
                    "(also for restarts and similar). It should contain all the "
                    "needed files for a KKR calc, only edited files should be "
                    "uploaded from the repository.")
            },
            })
        return use_dict

    def _prepare_for_submission(self, tempfolder, inputdict):
        """
        Create input files.

            :param tempfolder: aiida.common.folders.Folder subclass where
                the plugin should put all its files.
            :param inputdict: dictionary of the input nodes as they would
                be returned by get_inputs_dict
        """
        
        has_parent = False        
        local_copy_list = []
        # Check inputdict
        try:
            parameters = inputdict.pop(self.get_linkname('parameters'))
        except KeyError:
            raise InputValidationError("No parameters specified for this "
                                       "calculation")
        if not isinstance(parameters, ParameterData):
            raise InputValidationError("parameters not of type "
                                       "ParameterData")
        try:
            code = inputdict.pop(self.get_linkname('code'))
        except KeyError:
            raise InputValidationError("No code specified for this "
                                       "calculation")
        try:
            parent_calc_folder = inputdict.pop(self.get_linkname('parent_folder'))
        except KeyError:
            raise InputValidationError("Voronoi files needed for KKR calculation, "
                                       "you need to provide a Parent Folder/RemoteData node.")
                                       
        if not isinstance(parent_calc_folder, RemoteData):
            raise InputValidationError("parent_calc_folder, if specified,"
                                           "must be of type RemoteData")

        # extract parent calculation
        parent_calcs = parent_calc_folder.get_inputs(node_type=JobCalculation)
        n_parents = len(parent_calcs)
        if n_parents != 1:
            raise UniquenessError(
                    "Input RemoteData is child of {} "
                    "calculation{}, while it should have a single parent"
                    "".format(n_parents, "" if n_parents == 0 else "s"))
            parent_calc = parent_calcs[0]
            has_parent = True
        if n_parents == 1:
            parent_calc = parent_calcs[0]
            has_parent = True         
        
        # check that it is a valid parent
        #self._check_valid_parent(parent_calc)


        # if voronoi calc do
        # check if folder from db given, or get folder from rep.
        # Parent calc does not has to be on the same computer.
        #TODO so far we copy every thing from local computer ggf if kkr we want to copy remotely

                
        # get StructureData node from Parent if Voronoi
        structure = None        
        self.logger.info("Get structure node from voronoi parent")
        if isinstance(parent_calc, VoronoiCalculation):
            self.logger.info("Parent is Voronoi calculation")
            try:            
                structure = parent_calc.get_inputs_dict()['structure']    
            except KeyError:
                # raise InputvaluationError # TODO raise some error
                self.logger.error('Could not get structure from Voronoi parent.')
                pass
        elif isinstance(parent_calc, KkrCalculation):
            self.logger.info("Parent is KKR calculation")
            #try:            
            self.logger.error('extract structure from KKR parent')
            structure = self.find_parent_struc(parent_calc)   
            #except KeyError:
            #    # raise InputvaluationError # TODO raise some error
            #    pass
            #    self.logger.info('Could not get structure from KKR parent.')
        else:
            self.logger.info("Parent is neither Voronoi nor KKR calculation!")
            self.logger.error('Could not get structure from parent.')
            raise ValidationError()
            
        if inputdict:
            self.logger.error('Unknown inputs for structure lookup')
            raise ValidationError("Unknown inputs")


        ###################################
        # Prepare Structure

        # Get the connection between coordination number and element symbol
        # maybe do in a differnt way
        
        _atomic_numbers = {data['symbol']: num for num,
                        data in PeriodicTableElements.iteritems()}
        
        # KKR wants units in bohr and relativ coordinates
        bravais = array(structure.cell)*a_to_bohr
        alat = get_alat_from_bravais(bravais)
        bravais = bravais/alat
        
        sites = structure.sites
        naez = len(sites)
        positions = []
        charges = []
        for site in sites:
            pos = site.position 
            #TODO convert to rel pos and make sure that type is rigth for script (array or tuple)
            relpos = array(pos) 
            positions.append(relpos)
            sitekind = structure.get_kind(site.kind_name)
            site_symbol = sitekind.symbol
            charges.append(_atomic_numbers[site_symbol])
            
        positions = array(positions)
        #TODO get empty spheres
        #TODO deal with alloys (CPA, VCA)
        #TODO default is bulk, get 2D from structure.pbc info (periodic boundary contitions)
        

        ######################################
        # Prepare keywords for kkr from input structure
        
        # get parameter dictionary
        input_dict = parameters.get_dict()
        # empty kkrparams instance (contains formatting info etc.)
        params = kkrparams()
        for key in input_dict.keys():
            params.set_value(key, input_dict[key])

        # Write input to file
        input_filename = tempfolder.get_abs_path(self._INPUT_FILE_NAME)
        params.set_multiple_values(BRAVAIS=bravais, ALATBASIS=alat, NAEZ=naez, ZATOM=charges, RBASIS=positions)
        
        #TODO check if parent is voronoi calculation, otherwise take input, right now takes only voronoi calculation
        if isinstance(parent_calc, VoronoiCalculation):
            self.logger.info('Overwriting EMIN with value from voronoi output')
            emin = parent_calc.res.EMIN
            params.set_value('EMIN', emin)
        
        params.fill_keywords_to_inputfile(output=input_filename)


        #################
        # Decide what files to copy
        if has_parent:
            # copy the right files #TODO check first if file, exists and throw
            # warning, now this will throw an error
            outfolderpath = parent_calc.out.retrieved.folder.abspath
            self.logger.info("out folder path {}".format(outfolderpath))
            
            copylist = []
            if isinstance(parent_calc, KkrCalculation):
                copylist = self._copy_filelist_kkr
                # TODO ggf copy remotely...
            if isinstance(parent_calc, VoronoiCalculation):
                copylist = [parent_calc._SHAPEFUN, 
                            parent_calc._OUT_POTENTIAL_voronoi]              
            
            for file1 in copylist:
                filename = file1
                if file1 == 'output.pot' or file1 == self._OUT_POTENTIAL:
                    filename = self._POTENTIAL
                local_copy_list.append((
                        os.path.join(outfolderpath, 'path', file1),
                        os.path.join(filename)))
            # TODO different copy lists, depending on the keywors input


        # Prepare CalcInfo to be returned to aiida
        calcinfo = CalcInfo()
        calcinfo.uuid = self.uuid
        calcinfo.local_copy_list = local_copy_list
        calcinfo.remote_copy_list = []
        
        # TODO retrieve list needs some logic, retrieve certain files, 
        # only if certain input keys are specified....
        calcinfo.retrieve_list = [self._DEFAULT_OUTPUT_FILE, 
                                  self._INPUT_FILE_NAME,
                                  self._POTENTIAL,
                                  self._SHAPEFUN,
                                  self._SCOEF,
                                  self._NONCO_ANGLES_OUT,
                                  self._OUT_POTENTIAL,
                                  self._OUTPUT_0_INIT,
                                  self._OUTPUT_000,
                                  self._OUT_TIMING_000]

        codeinfo = CodeInfo()
        codeinfo.cmdline_params = []
        codeinfo.code_uuid = code.uuid
        codeinfo.stdout_name = self._DEFAULT_OUTPUT_FILE
        calcinfo.codes_info = [codeinfo]

        return calcinfo


    def _check_valid_parent(self, calc):
        """
        Check that calc is a valid parent for a FleurCalculation.
        It can be a VoronoiCalculation, KKRCalculation
        """

        try:
            if (((not isinstance(calc, VoronoiCalculation)))
                            and (not isinstance(calc, KkrCalculation))):
                raise ValueError("Parent calculation must be a VoronoiCalculation, a "
                                 "KkrCalculation or a CopyonlyCalculation")
        except ImportError:
            if ((not isinstance(calc, KkrCalculation)) ):
                raise ValueError("Parent calculation must be a VoronoiCalculation or "
                                 "a KkrCalculation")


    def use_parent_calculation(self, calc):
        """
        Set the parent calculation of KKR,
        from which it will inherit the outputsubfolder.
        The link will be created from parent RemoteData to KkrCalculation
        """
        from aiida.common.exceptions import NotExistent

        self._check_valid_parent(calc)

        remotedatas = calc.get_outputs(type=RemoteData)
        if not remotedatas:
            raise NotExistent("No output remotedata found in "
                                  "the parent")
        if len(remotedatas) != 1:
            raise UniquenessError("More than one output remotedata found in "
                                  "the parent")
        remotedata = remotedatas[0]

        self._set_parent_remotedata(remotedata)


    def _set_parent_remotedata(self, remotedata):
        """
        Used to set a parent remotefolder in the restart of fleur.
        """
        if not isinstance(remotedata,RemoteData):
            raise ValueError('remotedata must be a RemoteData')

        # complain if another remotedata is already found
        input_remote = self.get_inputs(node_type=RemoteData)
        if input_remote:
            raise ValidationError("Cannot set several parent calculation to a "
                                  "KKR calculation")

        self.use_parent_folder(remotedata)

        
    def get_struc(self, parent_calc):
        """
        Get structure from a parent_folder (result of a calculation, typically a remote folder)
        """
        return parent_calc.inp.structure
        
        
    def has_struc(self, parent_folder):
        """
        Check if parent_folder has structure information in its input
        """
        success = True
        try:
            parent_folder.inp.structure
        except:
            success = False
        if success:
            print('struc found')
        else:
            print('no struc found')
        return success
        
        
    def get_remote(self, parent_folder):
        """
        get remote_folder from input if parent_folder is not already a remote folder
        """
        parent_folder_tmp0 = parent_folder
        try:
            parent_folder_tmp = parent_folder_tmp0.inp.remote_folder
            print('input has remote folder')
        except:
            #TODO check if this is a remote folder
            parent_folder_tmp = parent_folder_tmp0
            print('input is remote folder')
        return parent_folder_tmp
        
        
    def get_parent(self, input_folder):
        """
        get the  parent folder of the calculation. If not parent was found return input folder
        """
        input_folder_tmp0 = input_folder
        try:
            parent_folder_tmp = input_folder_tmp0.inp.parent_calc_folder
            print('input has parent folder')
        except:
            parent_folder_tmp = input_folder_tmp0
            print('input is parent folder')
        return parent_folder_tmp
        
        
    def find_parent_struc(self, parent_folder):
        """
        Find the Structure node recuresively in chain of parent calculations (structure node is input to voronoi calculation)
        """
        iiter = 0
        Nmaxiter = 100
        parent_folder_tmp = self.get_remote(parent_folder)
        while not self.has_struc(parent_folder_tmp) and iiter<Nmaxiter:
            parent_folder_tmp = self.get_remote(self.get_parent(parent_folder_tmp))
            iiter += 1
        print(iiter)
        if self.has_struc(parent_folder_tmp):
            struc = self.get_struc(parent_folder_tmp)
            return struc
        else:
            print('struc not found')
            
        
        

    #parent_folder_tmp = parent_folder.copy()