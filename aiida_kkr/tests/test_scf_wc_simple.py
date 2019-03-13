#!/usr/bin/env python

import pytest
from dbsetup import *

# helper function
def print_clean_inouts(node):
    from pprint import pprint
    inputs = node.get_inputs_dict()
    outputs = node.get_outputs_dict()
    for key in outputs.keys():
        try:
            int(key.split('_')[-1])
            has_id = True
        except:
            has_id = False
        if 'CALL' in key or 'CREATE' in key or has_id:
            outputs.pop(key)
    print 'inputs:'
    pprint(inputs)
    print '\noutputs:'
    pprint(outputs)


# tests
@pytest.mark.usefixtures("aiida_env")
class Test_scf_workflow():
    """
    Tests for the scf workfunction
    """
    
    def test_scf_wc_Cu_simple(self):
        """
        simple Cu noSOC, FP, lmax2 full example using scf workflow
        """
        from aiida.orm import Code, load_node, DataFactory
        from aiida.work import run
        from masci_tools.io.kkr_params import kkrparams
        from aiida_kkr.workflows.kkr_scf import kkr_scf_wc
        from pprint import pprint
        from numpy import array
       
        ParameterData = DataFactory('parameter')
        StructureData = DataFactory('structure')

        from aiida.orm.implementation.django.code import Code
        from aiida.orm.computers import Computer
        from aiida.orm.querybuilder import QueryBuilder

        # prepare computer and code (needed so that 
        prepare_code(voro_codename, codelocation, computername, workdir)
        prepare_code(kkr_codename, codelocation, computername, workdir)

        # create structure
        alat = 6.83 # in a_Bohr
        abohr = 0.52917721067 # conversion factor to Angstroem units
        # bravais vectors
        bravais = array([[0.5, 0.5, 0.0], [0.5, 0.0, 0.5], [0.0, 0.5, 0.5]])
       
        a = 0.5*alat*abohr
        Cu = StructureData(cell=[[a, a, 0.0], [a, 0.0, a], [0.0, a, a]])
        Cu.append_atom(position=[0.0, 0.0, 0.0], symbols='Cu')
       
        Cu.store()
        print(Cu)
       
        # here we create a parameter node for the workflow input (workflow specific parameter) and adjust the convergence criterion.
        wfd = kkr_scf_wc.get_wf_defaults()
       
        wfd['convergence_criterion'] = 10**-4
        wfd['check_dos'] = False 
        wfd['kkr_runmax'] = 5
        wfd['nsteps'] = 50 
        wfd['queue_name'] = queuename
        wfd['resources']['num_machines'] = 1 
        wfd['use_mpi'] = True
       
        wfd['num_rerun'] = 2
        wfd['natom_in_cls_min'] = 20
       
        KKRscf_wf_parameters = ParameterData(dict=wfd)
       
        # The scf-workflow needs also the voronoi and KKR codes to be able to run the calulations
        VoroCode = Code.get_from_string(voro_codename+'@'+computername)
        KKRCode = Code.get_from_string(kkr_codename+'@'+computername)
       
        # Finally we use the kkrparams class to prepare a valid set of KKR parameters that are stored as a ParameterData object for the use in aiida
        ParaNode = ParameterData(dict=kkrparams(LMAX=2, RMAX=7, GMAX=65, NSPIN=1, RCLUSTZ=1.9).get_dict())
       
        label = 'KKR-scf for Cu bulk'
        descr = 'KKR self-consistency workflow for Cu bulk'

        # create process builder to set parameters
        builder = kkr_scf_wc.get_builder()
        builder.calc_parameters = ParaNode
        builder.voronoi = VoroCode
        builder.kkr = KKRCode
        builder.structure = Cu
        builder.wf_parameters = KKRscf_wf_parameters
        builder.label = label
        builder.description = descr

        # now run calculation
        from aiida.work.launch import run, submit
        out = run(builder)
       
        # load node of workflow
        print out
        n = out['output_kkr_scf_wc_ParameterResults']
       
        print '\noutputs of workflow\n-------------------------------------------------'
        pprint(n.get_outputs_dict())
       
        # get output dictionary
        out = n.get_dict()
        print '\n\noutput dictionary:\n-------------------------------------------------'
        pprint(out)
       
        # finally check some output
        print '\n\ncheck values ...\n-------------------------------------------------'
       
        print 'voronoi_step_success', out['voronoi_step_success']
        assert out['voronoi_step_success']
       
        print 'kkr_step_success', out['kkr_step_success']
        assert out['kkr_step_success']
       
        print 'successful', out['successful']
        assert out['successful']
       
        print 'error', out['errors']
        assert out['errors'] == []
       
        print 'warning', out['warnings']
        assert out['warnings'] == []
       
        print 'convergence_reached', out['convergence_reached']
        assert out['convergence_reached']
       
        print 'convergence_value', out['convergence_value']
        assert out['convergence_value'] < 10**-4
       
        print 'charge_neutrality', abs(out['charge_neutrality'])
        assert abs(out['charge_neutrality']) < 5*10**-4
       
        print 'used_higher_accuracy', out['used_higher_accuracy']
        assert out['used_higher_accuracy']
       
        print '\ndone with checks\n'
 
#run test manually
if __name__=='__main__':
   from aiida import is_dbenv_loaded, load_dbenv
   if not is_dbenv_loaded():
      load_dbenv()
   Test = Test_scf_workflow()
   Test.test_scf_wc_Cu_simple()
