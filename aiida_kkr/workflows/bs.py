#!/usr/bin/env python
# coding: utf-8

# In[2]:


####  #!/usr/bin/env python
####  # -*- coding: utf-8 -*-

from six.moves import range
import numpy as np
from aiida.orm import Code,  Dict, RemoteData, StructureData, Float
from aiida.orm import XyData, WorkChainNode, load_node, CalcJobNode, ArrayData, KpointsData
from aiida.engine import WorkChain, if_, ToContext, submit
from aiida.engine import CalcJob, calcfunction
from masci_tools.io.kkr_params import kkrparams
from aiida_kkr.tools.common_workfunctions import test_and_get_codenode, get_parent_paranode, update_params_wf, get_inputs_kkr
from aiida_kkr.calculations.kkr import KkrCalculation
from aiida_kkr.calculations.voro import VoronoiCalculation
from aiida.common.exceptions import InputValidationError, ConfigurationError
from aiida_kkr.tools.save_output_nodes import create_out_dict_node
from aiida.tools.data.array.kpoints import get_explicit_kpoints_path
__copyright__ = u"FZJ"
__license__ = "MIT license"
__version__ = "0.1.0"
__contributors__ = u"Rubel Mozumder"


# In[3]:


class kkr_bs_wc(WorkChain):
    """
    Workchain for BandStructure calculation, starting from RemoteFolderData the previous converged KKR calculation remote folder data

    inputs:
    :param wf_parameters: (Dict), (optional); Workchain Specifications, contains npt2, tempr, emin(ev), emax(ev), RCLUSTZ
                          keys. The Energy emin and emax are the energy difference from the fermi energy.

    :param options: (Dict), (optional); Computer Specifications, Schedualer command, parallel or serial
    :param kpoints: (KpointsData),(optional); Kpoints data type from thestructure,
                                   but not mendatory as it can be extrruct from structure internaly from the remote data
    :param remote_data: (RemoteData)(mendaory); From the previous kkr-converged calcualtion.
    :param kkr: (Code)(mendaory); KKR code specifiaction
    :param label: (Str) (optional) ; label for WC but will be found in the "result_wf" output 
                                     Dict as 'BS_wf_label' key
    :param description: (Str) (optional) : description for WC but will be found in the "result_wf" output 
                                     Dict as 'BS_wf_description' key


    returns:
    :out BS_Data : (ArrayData) ; Consist of (BlochSpectralFunction), k_points (list), energy_points (list), special_kpoints(dict)
    :out result_wf: (Dict); work_chain_specifications node, BS_data node, remote_folder node  
    """

    _wf_version = __version__
    _wf_label = 'kkr_BandStructure_wc'
    _wf_description = """Workflow for a bandstructure calculation starting eithe from a structure with automatic voronoi'
                        calculation or a valid RemoteData of a previous calculation."""
    _wf_params_default = {
                        'EMIN':13,  # Energy below the fermi surface for energy contour in ev unit
                        'EMAX': 15,     # Energy over the fermi surface for energy contour in ev unit
                        "NPT2": 200,   # Energy points in the energy contour
                        "RCLUSTZ": 2.3,
                        'TEMPR': 50.   # temperature
                          }
    _wf_option_default = {'max_wallclock_seconds': 36000,
                          'resources': {'num_machines': 1},
                          'withmpi': True,
                          'queue_name': ''
                         }

    @classmethod
    def get_wf_params_defaults(self, silent=False):
        if not silent: print('Version of the wf pparameters  {}'.format(self._wf_version))
        return self._wf_params_default

    @classmethod
    def define(cls, spec):
        super(kkr_bs_wc, cls).define(spec)
        # here inputs are defined
        spec.input("wf_parameters", valid_type = Dict, required = False,default=lambda: Dict(self._wf_params_default))
        spec.input("options", valid_type=Dict, required=False,default=lambda: Dict(dict=cls._wf_option_default))
        spec.input("remote_data", valid_type=RemoteData, required=True)
        spec.input("kkr", valid_type=Code, required=True)
        spec.input("kpoints", valid_type=KpointsData, required = False)
        spec.input("label", valid_type=Str, required=False)
        spec.input("description", valid_type=Str, required=False)
        
        # Here outputs are defined
        spec.output("results_wf", valid_type=Dict, required=True)        
        spec.output('BS_Data', valid_type=ArrayData, required=True)

        # Here outlines are being specified
        spec.outline(
            # For initialiging workflow
            cls.start,
            cls.validate_input,
            cls.set_params_BS,
            cls.get_BS,
            cls.return_results
        )
        # definition of exit code in case something goes wrong in this workflow
        spec.exit_code(161, 'ERROR_NO_INPUT_REMOTE_DATA', 'No remote_data was provided as Input')
        spec.exit_code(162, 'ERROR_KKRCODE_NOT_CORRECT', 'The code you provided for kkr does not use the plugin kkr.kkr')
        spec.exit_code(163, 'ERROR_CALC_PARAMETERS_INVALID', 'calc_parameters given are not consistent! Hint: did you give an unknown keyword?')
        spec.exit_code(164, 'ERROR_CALC_PARAMETERS_INCOMPLETE', 'calc_parameters not complete')
        spec.exit_code(165, 'ERROR_BS_CALC_FAILED', 'KKR Band Structure calculation failed')
        spec.exit_code(166, 'ERROR_NO_KPOINTS_EXTRACTED', 'No K-POINTS can be extracted from the structure data')
        spec.exit_code(167, 'ERROR_INCORRECT_KPOINTS_EXTRACTED', 'No K-POINTS can be extracted from the primtive structure data rather conventional structure data')
        spec.exit_code(168, 'ERROR_INVALID_REMOTE_DATA_TPYE','Input remote_data node neither output of a KKR/voronoi calculation nor of kkr_scf_wc workflow')
        
        
    def start(self):
        self.report('INFO: started KKR Band Structure workflow version {}'
                    ''.format(self._wf_version))
        wf_dict = self.inputs.wf_parameters.get_dict()
        options_dict = self.inputs.options.get_dict()
        if wf_dict == {}:
            self.report('INFO: Using default wf parameter')
            wf_dict = self._wf_params_default
        if options_dict == {}:
            self.report('INFO: Using default wf Options')
            options_dict = self._wf_option_default
        self.ctx.withmpi = options_dict.get('withmpi', self._wf_option_default['withmpi'])
        self.ctx.resources = options_dict.get('resources', self._wf_option_default['resources'])
        self.ctx.max_wallclock_seconds = options_dict.get('max_wallclock_seconds', self._wf_option_default['max_wallclock_seconds'])
        self.ctx.queue = options_dict.get('queue_name', self._wf_option_default['queue_name'])
        self.ctx.custom_scheduler_commands = options_dict.get('custom_scheduler_commands', '')
        self.ctx.BS_params_dict = wf_dict
        self.ctx.BS_kkrparams = None # is set in set_params_BS
        self.ctx.BS_kpoints = None
        self.ctx.description_wf = self.inputs.get('description', self._wf_description)
        self.ctx.label_wf = self.inputs.get('label', self._wf_label)
        self.report('INFO: use the following parameter:\n'
                    'withmpi: {}\n'
                    'Resources: {}\n'
                    'Walltime (s): {}\n'
                    'queue name: {}\n'
                    'scheduler command: {}\n'
                    'description_wf: {}\n'
                    'label_wf: {}\n'
                    'BS_params: {}\n'.format(self.ctx.withmpi, self.ctx.resources, self.ctx.max_wallclock_seconds,
                                              self.ctx.queue, self.ctx.custom_scheduler_commands,
                                              self.ctx.description_wf, self.ctx.label_wf,
                                              self.ctx.BS_params_dict))
    
        self.ctx.successful = True
        self.ctx.errors = []

    def validate_input(self):
        """
        # validate input and find out which path ( converged kkr calc or wf ) to take
        # return True means run voronoi if false run kkr directly
        """
        inputs = self.inputs
        if 'remote_data' in inputs:
            input_ok = True
        else:
            input_ok = False
            return self.exit_codes.ERROR_NO_INPUT_REMOTE_DATA
        input_remote = self.inputs.remote_data
        parents = input_remote.get_incoming(node_class=CalcJobNode)
        nparents = len(parents.all_link_labels())

        if nparents!=1:
            # extract parent workflow and get uuid of last calc from output node
            parent_workflow = input_remote.inputs.last_RemoteData
            if not isinstance(parent_workflow, WorkChainNode):
                return self.exit_codes.ERROR_INVALID_REMOTE_DATA_TPYE

            parent_workflow_out = parent_workflow.outputs.output_kkr_scf_wc_ParameterResults
            uuid_last_calc = parent_workflow_out.get_dict().get('last_calc_nodeinfo').get('uuid')
            last_calc = load_node(uuid_last_calc)

            if not isinstance(last_calc, KkrCalculation) and not isinstance(last_calc, VoronoiCalculation):
                return self.exit_code.ERROR_INVALID_REMOTE_DATA_TPYE
                
            # overwrite remote_data node with extracted remote folder
            output_remote = last_calc.outputs.remote_folder

            self.inputs.remote_data = output_remote
        # To validate for kpoints
        if "kpoints" in inputs:
            self.ctx.BS_kpoints = 'kpoints'
            input_ok = True
        else:
            struc_kkr, remote_voro = VoronoiCalculation.find_parent_structure(self.inputs.remote_data)
            output = get_explicit_kpoints_path(struc_kkr)
            primitive_struc = output['primitive_structure']
            kpoints_ok = True 
            
            #check if primitive_structure and input structure are identical:
            maxdiff_cell = sum(abs(np.array(primitive_struc.cell) - np.array(struc_kkr.cell))).max()
            
            if maxdiff_cell>3*10**-9:
                print('Error in cell : {}'.format(maxdiff_cell))
                self.report('WARNING : The structure data from the voronoi calc is not the primitive structure type and in come cases it is medatory')
                self.ctx.structure_data = 'conventional_unit_cell '
            else:
                self.ctx.structure_data = 'primitive_unit_cell'
            
            if not kpoints_ok:
                return self.exit_codes.ERROR_INCORRECT_KPOINTS_EXTRACTED
            else:
                kpts = get_explicit_kpoints_path(struc_kkr).get('explicit_kpoints')
            
            self.ctx.BS_kpoints = kpts
            if isinstance(KpointsData(), type(kpts)):
                input_ok = True
            else:
                input_ok = False
                return self.exit_codes.ERROR_NO_KPOINTS_EXTRACTED

        # To validate for kkr    
        if 'kkr' in inputs:
            try:
                test_and_get_codenode(inputs.kkr, 'kkr.kkr', use_exceptions=True)
            except ValueError:
                input_ok = False
                return self.exit_codes.ERROR_KKRCODE_NOT_CORRECT

        # set self.ctx.input_params_KKR
        self.ctx.input_params_KKR = get_parent_paranode(self.inputs.remote_data)
        
        self.report('The validation input_ok {}'.format(input_ok))

    def set_params_BS(self):
        from masci_tools.io.common_functions import get_Ry2eV
        evscal = get_Ry2eV()
        params = self.ctx.input_params_KKR
        
        
        input_dict = params.get_dict()
        para_check = kkrparams()
        try:
            for key, val in input_dict.items():
                para_check.set_value(key, val, silent=True)
        except:
            return self.exit_codes.ERROR_CALC_PARAMETERS_INVALID
        label = ''
        descr = '(pk - {}, and uuid - {})'.format(self.inputs.remote_data.pk, self.inputs.remote_data.uuid)

        missing_list = para_check.get_missing_keys(use_aiida=True)

        if missing_list != []:
            kkrdefaults = kkrparams.get_KKRcalc_parameter_defaults()[0]
            kkrdefaults_updated = []
            for key_default, val_default in list(kkrdefaults.items()):
                if key_default in missing_list:
                    para_check.set_value(key_default, val_default)
                    kkrdefaults_updated.append(key_default)
                    missing_list.remove(key_default)
            if len(missing_list)>0:
                self.report('ERROR: calc_parameters misses keys: {}'.format(missing_list))
                return self.exit_codes.ERROR_CALC_PARAMETERS_INCOMPLETE
            else:
                self.report('updated KKR parameter node with default values: {}'.format(kkrdefaults_updated))
                label = 'add_defaults_'
                descr = 'added missing default keys, '
        ##+++ Starts to add the NTP2, EMAX and EMIN from the 
        econt_new = self.ctx.BS_params_dict
        kkr_calc = self.inputs.remote_data.get_incoming().first().node
        ef = kkr_calc.outputs.output_parameters.get_dict()['fermi_energy'] # unit in Ry
        self.ctx.fermi_energy = ef ## in Ry unit

        # Set BS params 
        try:
            for key, val in econt_new.items():
                if key=='nepts' or key=='NPT2':
                    key = 'NPT2'
                    # add IEMXD which has to be big enough
                    print('setting IEMXD', val)
                    para_check.set_value('NPT2', val, silent=True)
                    para_check.set_value('IEMXD', val, silent=True)
                    
                elif key=='emin' or key=='EMIN':
                    key = 'EMIN'
                    new_val = (ef - val)/evscal # converting the Energy value to eV while the fermi_energy in Ry
                    para_check.set_value(key, new_val, silent=True)

                    para_check.set_value(key, new_val, silent=True)
                elif key=='emax' or key== 'EMAX':
                    key = 'EMAX'
                    new_val = ( ef + val)/evscal # Converting to the ev (unit of the energy)
                    para_check.set_value(key, new_val, silent=True)
                elif key=='tempr' or key=='TEMPR':
                    key = 'TEMPR'
                    para_check.set_value(key, val, silent=True)
                elif key=='RCLUSTZ' or key=='rclustz':
                    key = 'RCLUSTZ'
                    para_check.set_value(key, val, silent=True)

        except:
            return self.exit_codes.ERROR_CALC_PARAMETERS_INVALID
        para_check.set_multiple_values(NPT1=0, NPT3=0, NPOL=0,)
        
        updatenode = Dict(dict=para_check.get_dict())
        updatenode.label = label+'KKRparam_BS'
        updatenode.description = 'KKR parameter node extracted from remote_folder' + descr + ' as well as wf_parameter input node.'

        paranode_BS = update_params_wf(self.ctx.input_params_KKR, updatenode)
        self.ctx.BS_kkrparams = paranode_BS

    def get_BS(self):
        label = 'KKR BS calc.'
        BS_dict = self.ctx.BS_params_dict
        key_list = list(BS_dict)
        description = 'User defined BandStructure parameters '
        for index in range(len(key_list)):
            description += '{}= {} ,'.format(key_list[index], BS_dict[key_list[index]])

        code = self.inputs.kkr
        remote = self.inputs.remote_data
        params = self.ctx.BS_kkrparams
        kpoints = self.ctx.BS_kpoints
        options = {"max_wallclock_seconds": self.ctx.max_wallclock_seconds,
                   "resources": self.ctx.resources,
                   "queue_name" : self.ctx.queue}#,
        if self.ctx.custom_scheduler_commands:
            options["custom_scheduler_commands"] = self.ctx.custom_scheduler_commands

        create_builder = KkrCalculation.get_builder()
        create_builder.parent_folder = remote
        create_builder.code = code
        create_builder.parameters = params
        create_builder.kpoints = kpoints
        create_builder.metadata.options = options

        BS_run = self.submit(KkrCalculation, **create_builder)
        self.ctx.last_calc = BS_run


        return ToContext(BS_run=BS_run)

    def return_results(self):
        """
        Collect results, parse BS_calc output and link output nodes to workflow node
        """

        caching_info = "INFO: cache_source of BS calc node: {}".format(self.ctx.BS_run.get_cache_source)
        print(caching_info)
        self.report(caching_info)

        if not self.ctx.BS_run.is_finished_ok:
            self.ctx.successful = False
            error = ('ERROR BS calculation failed somehow it is '
                    'in state {}'.format(self.ctx.BS_run.process_state))
            print(error)
            from pprint import pprint
            pprint(self.ctx.BS_run.attributes)
            print('stdout', self.ctx.BS_run.get_scheduler_stdout())
            print('stderr', self.ctx.BS_run.get_scheduler_stderr())
            self.report(error)
            self.ctx.errors.append(error)
            return self.exit_codes.ERROR_BS_CALC_FAILED

        # create dict to store results of workflow output
        outputnode_dict = {}
        outputnode_dict['workflow_name'] = self.__class__.__name__
        outputnode_dict['workflow_version'] = self._wf_version
        outputnode_dict['withmpi'] = self.ctx.withmpi
        outputnode_dict['resources'] = self.ctx.resources
        outputnode_dict['max_wallclock_seconds'] = self.ctx.max_wallclock_seconds
        outputnode_dict['queue_name'] = self.ctx.queue
        outputnode_dict['custom_scheduler_commands'] = self.ctx.custom_scheduler_commands
        outputnode_dict['BS_params'] = self.ctx.BS_params_dict
        outputnode_dict['structure_type'] = self.ctx.structure_data
        
        
        outputnode_dict['BS_wf_description'] = self.ctx.description_wf
        outputnode_dict['BS_wf_label'] = self.ctx.label_wf
        try:
            outputnode_dict['nspin'] = self.ctx.BS_run.res.nspin
        except:
            error = "ERROR: nspin not extracted"
            self.report(error)
            self.ctx.successful = False
            self.ctx.errors.append(error)
        outputnode_dict['successful'] = self.ctx.successful
        outputnode_dict['list_of_errors'] = self.ctx.errors

        # create output node with data-provenance
        outputnode = Dict(dict=outputnode_dict)
        outputnode.label = 'kkr_BS_wc_results'
        outputnode.description = 'Contains the info of the WC'

        self.report("INFO: create Banstructure results nodes")
        try:
            self.report("INFO: create Bandstructure results nodes. BS calc retrieved node={}".
                        format(self.ctx.BS_run.outputs.retrieved))
            has_BS_run = True
        except AttributeError as e:
            self.report("ERROR: No Bandstructure calc retrieved node found")
            self.report("Caught AttributeError {}".format(e))
            return self.exit_codes.ERROR_BS_CALC_FAILED
        
        if has_BS_run:
            BS_retrieved = self.ctx.BS_run.outputs.retrieved
            
        ef = self.ctx.fermi_energy  # in Ry unit
        kpoints = self.ctx.BS_kpoints
        
      # Here outdict dictionary has been created to set the Dict result_wf, BS_data
      # to the output(spec.output) of the wf
        outdict = {}
        if has_BS_run:
            ArraData = parse_BS_data(BS_retrieved, Float(ef), kpoints)
            outdict['BS_Data'] = ArraData['BS_Data'] 

        # link to the BS output nodes
        link_nodes = outdict.copy()
      
        outdict['results_wf'] = create_out_dict_node(outputnode, **link_nodes)

    # create links to output nodes
        for link_name, node in outdict.items():
            self.out(link_name, node)

        self.report("INFO: done with BS_workflow!\n")

@calcfunction
def parse_BS_data(retrieved_folder, fermi_level, kpoints):
    from masci_tools.io.common_functions import get_Ry2eV
    from aiida.plugins import DataFactory
    import numpy as np

    eVscale = get_Ry2eV()  
    
    retrieved_list = retrieved_folder.list_object_names()
    qdos_file_list = [i for i in retrieved_list if 'qdos.' in i]
    q_vec_file = 'qvec.dat'

    if q_vec_file in retrieved_list:
        file_opened = retrieved_folder.open(q_vec_file)
        q_vec = np.loadtxt(file_opened, skiprows=1 )

    else:
        print('{} file is not present in the retrived folder'.format(q_vec_file))
    no_q_vec = len(q_vec[:,0])

    num_qdos_files = len(qdos_file_list)

    with retrieved_folder.open(qdos_file_list[0]) as f:
        total_qdos = np.loadtxt(f)

    for i in qdos_file_list[1:]:
        with retrieved_folder.open(i) as f:
            loaded_file = np.loadtxt(f)
            total_qdos[:,5:] += loaded_file[:,5:]
    
    ef = fermi_level.value # in Ry unit
    total_qdos[:,0] = (total_qdos[:,0]-ef)*eVscale 
    eng_points = set(total_qdos[:,0])
    eng_points = list(eng_points)
    no_eng_points = len(eng_points)

    qdos_intensity = np.ndarray(shape = (no_eng_points, no_q_vec))
    for ne in range(np.shape(qdos_intensity)[0]):
        nk = np.shape(qdos_intensity)[1]

        qdos_intensity[ne,:] = total_qdos[ ne*nk : (ne+1)*nk, 5 ]/eVscale 

    qdos_intensity = qdos_intensity.T # setting eng-kpts corresponds to x-y asix
    q_vec = np.asarray(q_vec) # converting q_vec into array
    eng_points = (np.asarray(eng_points)) # converting eng_popints into array in Ry unit
    
    klbl_dict = dict(kpoints.labels) # Special k-points
    # To save into the ArrayData
    ArrayData = DataFactory('array')
    array = ArrayData()
    array.set_array('BlochSpectralFunction', qdos_intensity)
    array.set_array('Kpts', q_vec)
    array.set_array('energy_points',eng_points)
    array.extras['k-labels'] = klbl_dict

    return {'BS_Data' : array}



                                         


# In[4]:


##++ Starts submision of kkr_BS_wf
from aiida import load_profile, get_profile
load_profile()
print(get_profile().name)
from aiida.engine import run
from aiida.orm import Code, load_node, load_code
from aiida.plugins import DataFactory
Str = DataFactory('str')

Dict = DataFactory('dict')
metadata_option_1 = {'max_wallclock_seconds': 36000,'resources':
              {'tot_num_mpiprocs': 48, 'num_machines': 1},
              'custom_scheduler_commands':
              '#SBATCH --account=jara0191\n\nulimit -s unlimited; export OMP_STACKSIZE=2g',
              'withmpi': True}
Dict_metadata_option_1 = Dict(dict=metadata_option_1)

calc_dos = load_node(203)
calc_kkr_converged = load_node(180)
remote_folder_kkr = calc_kkr_converged.outputs.remote_folder

                        
wf_parameters_dict = {'NPT2' : 200,'EMIN' : 20, "RCLUSTZ": 2.3, 'EMAX' :13 , 'TEMPR' : 50}
wf_parameters = Dict(dict=wf_parameters_dict)#calc_kkr_converged.inputs.parameters#.get_dict()
kkr = Code.get_from_string('kkrhost@claix18')
inputs_name = { 'wf_parameters':wf_parameters, 'options':Dict_metadata_option_1, 'remote_data':remote_folder_kkr,
           'kkr':kkr }
submition_kkr_BS_wf = run(kkr_bs_wc, **inputs_name)
## Ends submision of the kkr_BS_wf                                    


# In[ ]:


flt = Float(4.5)
type(flt.value)
type(flt)


# In[28]:


from masci_tools.io.common_functions import get_Ry2eV
eVscale = get_Ry2eV()

# type(eVscale(1))
type(eVscale)
eVscale


# In[33]:


def ev_To_Ry(value = 1 ):

    return float(value/13.6056980659)
ev_To_Ry(13.6056980659)


# In[ ]:



