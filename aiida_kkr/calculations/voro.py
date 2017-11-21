# -*- coding: utf-8 -*-
"""
Input plug-in for a voronoi calculation.
"""

from numpy import array
from aiida.orm.calculation.job import JobCalculation
from aiida.common.utils import classproperty
from aiida.common.exceptions import (InputValidationError, ValidationError)
from aiida.common.datastructures import (CalcInfo, CodeInfo)
from aiida.common.constants import elements as PeriodicTableElements
from aiida.orm import DataFactory
#from aiida_kkr.tools.kkrcontrol import write_kkr_inputcard_template, fill_keywords_to_inputcard, create_keyword_default_values
from aiida_kkr.tools.kkr_params import kkrparams
from aiida_kkr.tools.common_functions import get_alat_from_bravais, get_Ang2aBohr

ParameterData = DataFactory('parameter')
StructureData = DataFactory('structure')
a_to_bohr = get_Ang2aBohr()

class VoronoiCalculation(JobCalculation):
    """
    AiiDA calculation plugin for a voronoi calculation (creation of starting potential and shapefun)
    .
    """

    def _init_internal_params(self):
        """
        Init internal parameters at class load time
        """
        # reuse base class function
        super(VoronoiCalculation, self)._init_internal_params()

        # Default input and output files
        self._DEFAULT_INPUT_FILE = 'inputcard' # will be shown with inputcat
        self._DEFAULT_OUTPUT_FILE = 'out_voronoi' #'shell output will be shown with outputca

        # List of mandatory input files
        self._INPUT_FILE_NAME = 'inputcard'
        #self._INPUTCARD = 'inputcard'
	
	# List of output files that should always be present
        self._OUTPUT_FILE_NAME = 'out_voronoi'
       
       # template.product entry point defined in setup.json
        self._default_parser = 'kkr.voroparser'
        
        # File names
        self._ATOMINFO = 'atominfo.dat'
        self._RADII = 'radii.dat'
        self._SHAPEFUN = 'shapefun'
        self._VERTICES = 'vertices.dat'
        self._OUT_POTENTIAL_voronoi = 'output.pot'

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
            "structure": {
                'valid_types': StructureData,
                'additional_parameter': None,
                'linkname': 'structure',
                'docstring':
                ("Use a node that specifies the input crystal structure ")
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
        # Check inputdict
        try:
            parameters = inputdict.pop(self.get_linkname('parameters'))
            print parameters
        except KeyError:
            raise InputValidationError("No parameters specified for this "
                                       "calculation")
        if not isinstance(parameters, ParameterData):
            raise InputValidationError("parameters not of type "
                                       "ParameterData")
        try:
            structure = inputdict.pop(self.get_linkname('structure'))
        except KeyError:
            raise InputValidationError("No structure specified for this "
                                       "calculation")
        if not isinstance(structure, StructureData):
            raise InputValidationError("structure not of type "
                                        "StructureData")
        
        try:
            code = inputdict.pop(self.get_linkname('code'))
        except KeyError:
            raise InputValidationError("No code specified for this "
                                       "calculation")
        if inputdict:
                raise ValidationError("Unknown inputs: {}".format(inputdict))


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
            
        # TODO get empty spheres
        positions = array(positions)
        
        ######################################
        # Prepare keywords for kkr
        # get parameter dictionary
        input_dict = parameters.get_dict()
        print 'input parameter dict', input_dict
        # empty kkrparams instance (contains formatting info etc.)
        params = kkrparams()
        print 'new kkrparams instance', params
        for key in input_dict.keys():
            params.set_value(key, input_dict[key])

        # Write input to file
        input_filename = tempfolder.get_abs_path(self._INPUT_FILE_NAME)
        params.set_multiple_values(BRAVAIS=bravais, ALATBASIS=alat, NAEZ=naez, ZATOM=charges, RBASIS=positions)
        params.fill_keywords_to_inputfile(output=input_filename)


        # Prepare CalcInfo to be returned to aiida
        calcinfo = CalcInfo()
        calcinfo.uuid = self.uuid
        calcinfo.local_copy_list = []
        calcinfo.remote_copy_list = []
        calcinfo.retrieve_list = [self._OUTPUT_FILE_NAME, self._ATOMINFO, self._RADII,
                                        self._SHAPEFUN, self._VERTICES, self._OUT_POTENTIAL_voronoi]

        codeinfo = CodeInfo()
        codeinfo.cmdline_params = []
        codeinfo.stdout_name = self._OUTPUT_FILE_NAME
        codeinfo.code_uuid = code.uuid
        calcinfo.codes_info = [codeinfo]

        return calcinfo
