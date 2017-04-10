#!/usr/bin/env python
import argparse, sys, os, traceback, sys, string, json, datetime, time, subprocess, re
import urllib2
from socket import error as SocketError
from distutils.version import LooseVersion
import errno
import pprint
import xml.etree.ElementTree
from bioblend import galaxy
from bioblend.galaxy import dataset_collections

polling_time=10 # seconds
library_upload_timeout=1800 # seconds
use_newer_galaxy_api=False
snvphyl_cli_version='1.3'

galaxy_api_key_name='--galaxy-api-key'

docker_fastq_dir='/snvphyl-data/fastq'
use_docker_fastq_dir=False

upload_fastqs_as_links=True

def get_script_path():
    """
    Gets the current script path.

    :return: The current script path.
    """

    return os.path.dirname(os.path.realpath(sys.argv[0]))

def get_command_line_string():
    """
    Gets the command line string.

    :return: The command-line as a string.
    """

    command_line_list=sys.argv[:]

    try:
        api_key_index = command_line_list.index(galaxy_api_key_name)
        command_line_list[api_key_index+1]='*****'
    except ValueError:
        pass

    return " ".join(command_line_list) 

def get_git_commit():
    """
    Gets the current git commit for this code (if any).

    :return: The current git commit, or 'unknown' if not available.
    """
    script_path=get_script_path()
    curr_wd=os.getcwd()
    git_commit='unknown'

    os.chdir(script_path)
    git_command_line=['git','rev-parse','HEAD']

    try:
        DEVNULL = open(os.devnull, 'w')
        git_commit_for_code=subprocess.check_output(git_command_line,stderr=DEVNULL).rstrip()
        
        if re.compile("^[a-f,0-9]+$").search(git_commit_for_code):
            git_commit = git_commit_for_code

    except subprocess.CalledProcessError:
        git_commit = 'unknown'
    finally:
        os.chdir(curr_wd)
        DEVNULL.close()

    return git_commit

def get_all_snvphyl_versions(settings_file):
    """
    Gets all versions of available SNVPhyl pipelines from the given settings file.

    :param settings_file:  The file with the different SNVPhyl pipelines settings.

    :return: All valid SNVPhyl pipeline versions.
    """

    settings_root=xml.etree.ElementTree.parse(settings_file).getroot()
    snvphyl_versions={}
    for snvphyl_workflow in settings_root:
        snvphyl_versions[snvphyl_workflow.attrib['version']]={'version':snvphyl_workflow.attrib['version']}
        if ('dockerContainer' in snvphyl_workflow.attrib):
            snvphyl_versions[snvphyl_workflow.attrib['version']]['dockerContainer']=snvphyl_workflow.attrib['dockerContainer']

    return snvphyl_versions

def load_snvphyl_settings(settings_file,snvphyl_version, workflow_type):
    """
    Loads up SNVPhyl settings from the given file for the specified version and workflow types.

    :param settings_file:  The file with SNVPhyl settings.
    :param snvphyl_version:  The version of SNVPhyl to load.
    :param workflow_type:  The particular type of workflow to load.

    :return: A combined list of the particular workflow settings and workflow parameters.
    """

    settings_root=xml.etree.ElementTree.parse(settings_file).getroot()
    workflows=settings_root.findall("./snvphylWorkflow[@version='"+snvphyl_version+"'][@type='"+workflow_type+"']")
    if (len(workflows) < 1):
        raise Exception('Error: not workflow found with entry "<snvphylWorkflow version="'+snvphyl_version+'" type="'+workflow_type+'"> elements in file '+settings_file)
    if (len(workflows) > 1):
        raise Exception('Error: invalid number of "<snvphylWorkflow version="'+snvphyl_version+'" type="'+workflow_type+'"> elements in file '+settings_file)

    workflow_settings=workflows[0]

    # load default parameters
    workflow_parameters={}
    for parameter in workflow_settings.findall("./parameters/parameter"):
        default_value = parameter.attrib['defaultValue']
        for tool_parameter in parameter.findall("./toolParameter"):
            tool_id = tool_parameter.attrib['toolId']
            parameter_names = tool_parameter.attrib['parameterName'].split('.')
            if (not tool_id in workflow_parameters):
                workflow_parameters[tool_id]={}
            entry=workflow_parameters[tool_id]
            set_parameter_value_from_multipart_name(parameter_names,default_value,entry)

    return (workflow_settings,workflow_parameters)

def set_parameter_value_from_multipart_name(parameter_names,value,entry):
    """
    Sets a value for a tool parameter in Galaxy from a multi-part name.

    :param parameter_names:  The particular parameter names.
    :param value:  The value to set.
    :param entry: The particular entry where the value should be overridden.

    :return: None.
    """

    last_name=parameter_names.pop()
    for name in parameter_names:
        if (not name in entry):
            entry[name] = {}
        entry = entry[name]
    entry[last_name]=value

def set_parameter_value(workflow_settings,workflow_parameters,parameter_name,parameter_value):
    """
    Sets a Galaxy tool parameter value from the passed settings and parameter information.

    :param workflow_settings:  The settings file for the workflow, storing default parameter values.
    :param workflow_parameters:  The particular parameters to set.
    :param parameter_name:  The name of the parameter to set.
    :param parameter_value:  The value of the parameter to use.

    :return: None.
    """

    for parameter in workflow_settings.findall("./parameters/parameter[@name='"+parameter_name+"']"):
        for tool_parameter in parameter.findall("./toolParameter"):
            tool_id = tool_parameter.attrib['toolId']
            parameter_names = tool_parameter.attrib['parameterName'].split('.')
            if (not tool_id in workflow_parameters):
                workflow_parameters[tool_id]={}

            # iterate over parameter entries, creating sub dictionaries if necessary
            entry=workflow_parameters[tool_id]
            set_parameter_value_from_multipart_name(parameter_names,parameter_value,entry)

            print "setting parameter {"+tool_id+", "+tool_parameter.attrib['parameterName']+", "+str(parameter_value)+"}"

def find_workflow_uuid(galaxy_workflows,uuid):
    """
    Finds a particular workflow with the given uuid.

    :param galaxy_workflows:  The list of workflows to search through.
    :param uuid:  The workflow uuid to search for.

    :return: The matching workflow.
    :throws: Exception if no such matching workflow.
    """

    workflow = None
    for w in galaxy_workflows:
        if w['latest_workflow_uuid'] == uuid:
            if workflow != None:
                raise Exception("Error: multiple workflows with uuid="+uuid+", please use --workflow-id to specify")
            else:
                workflow=w
    return workflow

def split_fastq(file):
    """
    Splits a fastq file name into the file name part, and extension part.

    :param file:  The file name to split.

    :return: The name and the suffix/extension.
    :throws: ValueError if name could not be split.
    """

    try:
        filename=os.path.split(file)[1]
        (name,ext)=filename.split('.',1)
        if (ext == 'fastq.gz' or
            ext == 'fastq' or 
            ext == 'fq' or
            ext == 'fq.gz'):
            return (name,file)
        else:
            return (None,None)
    except ValueError:
        return (None,None) 

def strip_end(text, suffix):
    """
    Strips out the suffix from the given text.

    :param text:  The text with the suffix.
    :param suffix:  The suffix to remove.

    :return: The text minus the suffix.
    """

    if not text.endswith(suffix):
        return text
    return text[:len(text)-len(suffix)]

def get_pair_single(name):
    """
    Given a fastq file name, determines if it's paired-end or single-end and returns the type + name.

    :param name:  The name to check.

    :return: The combined file type ('single', 'forward', or 'reverse') and the name minus the direction-identifying part of the file name.
    """

    if name.endswith('_1'):
        return ('forward', strip_end(name,'_1'))
    elif name.endswith('_R1'):
        return ('forward', strip_end(name,'_R1'))
    elif name.endswith('_2'):
        return ('reverse', strip_end(name,'_2'))
    elif name.endswith('_R2'):
        return ('reverse', strip_end(name,'_R2'))
    elif name.endswith('_R1_001'):
        return ('forward', strip_end(name,'_R1_001'))
    elif name.endswith('_R2_001'):
        return ('reverse', strip_end(name,'_R2_001'))
    else:
        return ('single',name)

def structure_fastqs(fastq_dir):
    """
    Given a directory of fastq files, determine which are paired-end or single-end and return structured objects containing the files.

    :param fastq_dir:  The directory containing the fastq files.

    :return: Separate dictionaries of 'fastq_single' and 'fastq_paired' containing the structured single/paired-end files.
    :throws: Exception if duplicate or missing file-pairs or if there is a mixture of paired-end and single-end data.
    """

    fastq_files={}

    # read in all fastq files
    for file in os.listdir(fastq_dir):
        (filename,path)=split_fastq(file)
        if (filename is not None and path is not None):
            (direction,name)=get_pair_single(filename)
            fastq_entry=fastq_files.get(name)
            if fastq_entry is None:
                fastq_files[name]={direction: os.path.join(fastq_dir,file)}
            else:
                if direction == 'single':
                    raise Exception('Error: file='+file+' is marked as \'single\', but already exists associated file='+fastq_entry['file'])
                elif direction == 'forward' and (fastq_entry.get('forward') is not None):
                    raise Exception('Error: file='+file+' is marked as \'forward\', but already exists associated file='+fastq_entry['file'])
                elif direction == 'reverse' and (fastq_entry.get('reverse') is not None):
                    raise Exception('Error: file='+file+' is marked as \'reverse\', but already exists associated file='+fastq_entry['file'])
                else:
                    fastq_entry[direction]=os.path.join(fastq_dir,file)

    # check data structure
    fastq_single={}
    fastq_paired={}
    print "Structuring data in directory '"+fastq_dir+"' like:"
    for name in sorted(fastq_files.iterkeys()):
        entry=fastq_files[name]
        single=entry.get('single')
        forward=entry.get('forward')
        reverse=entry.get('reverse')

        if single is not None:
            fastq_single[name]=entry
            print name+': single {'+single+'}'
        elif forward is not None and reverse is not None:
            fastq_paired[name]=entry
            print name+': paired {forward: '+forward+', reverse: '+reverse+'}'
        else:
            filename=''
            if (forward is None):
                filename=reverse
            else:
                filename=forward

            fastq_single[name]={'single':filename}
            print name+': single {'+filename+'}'

    if fastq_single and fastq_paired:
        raise Exception("Error: mixture of single-end and paired-end data is currently unsupported")

    return (fastq_single,fastq_paired)

def find_workflow_steps(tool_id,steps):
    """
    Finds appropriate steps in workflow given tool id.

    :param tool_id: The tool id to search.
    :param steps: Dictionary of steps in workflow.

    :return: List of matching steps.
    """

    matches=[]
    for step in steps:
        if (steps[step]['tool_id'] == tool_id):
            matches.append(steps[step])

    return matches

def upload_fastqs_single(gi,history_id,fastq_single):
    """
    Uploads the given single-end fastq files to a Galaxy history.

    :param gi:  Galaxy instance.
    :param history_id:  History id to upload into.
    :param fastq_single: Map of single-end fastq names to 'single' paths for files to upload.

    :return:  Map of fastq names to history ids in Galaxy for each file.
    """

    single_elements=[]

    for name in sorted(fastq_single.iterkeys()):
        fastq_file=fastq_single[name]['single']
        
        print 'Uploading '+fastq_file
        file_galaxy=gi.tools.upload_file(fastq_file,history_id, file_type='fastqsanger')
        file_id=file_galaxy['outputs'][0]['id']

        single_elements.append(dataset_collections.HistoryDatasetElement(name=name,id=file_id))

    return single_elements

def upload_fastq_collection_single(gi,history_id,fastq_single):
    """
    Uploads given fastq files to the Galaxy history and builds a dataset collection.

    :param gi:  Galaxy instance.
    :param history_Id:  History id to upload into.
    :param fastq_single:  Single-end files to upload.

    :return: The dataset collection id for the constructed dataset.
    """

    single_elements=[]
    if (upload_fastqs_as_links):
        created_library=gi.libraries.create_library("SNVPhyl Library Dataset-"+str(time.time()))
        single_elements=upload_fastqs_library_single(gi,history_id,created_library['id'],fastq_single)
    else:
        single_elements=upload_fastqs_single(gi,history_id,fastq_single)

    # construct single collection
    single_collection_name="single_datasets"
    print "Building dataset collection named "+single_collection_name
    collection_response_single = gi.histories.create_dataset_collection(
        history_id=history_id,
        collection_description=dataset_collections.CollectionDescription(
            name=single_collection_name,
            type="list",
            elements=single_elements
        )
    )

    return collection_response_single['id']

def upload_fastqs_to_history_via_library(gi,history_id,library_id,fastqs_to_upload):
    """
    Uploads the given fastq files to a Galaxy History via a Dataset Library.
    This is required for linking instead of copying, as that can only be done via a Dataset Library.

    :param gi:  Galaxy instance.
    :param history_id:  History id to upload into.
    :param library_id:  Library id to upload into.
    :param fastqs_to_upload: Map of fastq names to paths for files to upload.

    :return:  Map of fastq names to history ids in Galaxy for each file.  Will block until Galaxy is finished processing.
    """

    uploaded_ids=[]
    fastq_library_ids={}
    fastq_history_ids={}

    for name in fastqs_to_upload.iterkeys():
        fastq_file=fastqs_to_upload[name]
        print 'Uploading as link '+fastq_file

        if (use_docker_fastq_dir):
            fastq_file=docker_fastq_dir+'/'+os.path.basename(fastq_file)

        response=gi.libraries.upload_from_galaxy_filesystem(library_id, fastq_file, file_type='fastqsanger', link_data_only='link_to_files')
        fastq_library_id=response[0]['id']

        fastq_library_ids[fastq_library_id] = name

    sys.stdout.write("Waiting for library datasets to finish processing...")
    sys.stdout.flush()

    finished_uploading=False
    uploaded_ids=fastq_library_ids.keys()
    reduced_uploaded_ids=uploaded_ids
    time_start_uploading=time.time()
    while (not finished_uploading):
        finished_uploading=True

        for dataset in uploaded_ids: 
            state=gi.libraries.show_dataset(library_id,dataset)['state']
            if (state == 'error'):
                raise Exception("Error uploading fastq file ("+fastq_library_ids[dataset]+", "+dataset+") to Galaxy Library "+library_id)
            elif (state == 'ok'):
                uploaded_history=gi.histories.upload_dataset_from_library(history_id,dataset)
                dataset_history_id=uploaded_history['id']

                name=fastq_library_ids[dataset]
                fastq_history_ids[name]=dataset_history_id

                reduced_uploaded_ids=list(reduced_uploaded_ids)
                reduced_uploaded_ids.remove(dataset)
            else:
                finished_uploading=False

        if (time.time()-time_start_uploading > library_upload_timeout):
            raise Exception("Error: Maximum upload timout of " + str(library_upload_timeout) + "s reached")

        uploaded_ids=reduced_uploaded_ids
        sys.stdout.write(str(len(uploaded_ids))+'.')
        sys.stdout.flush()
        time.sleep(2)
    print 'done'
    
    return fastq_history_ids

def upload_fastqs_library_paired(gi,history_id,library_id,fastq_paired):
    """
    Uploads the given paired-end fastq files to a Galaxy history via a dataset library.

    :param gi:  Galaxy instance.
    :param history_id:  History id to upload into.
    :param library_id:  Library id to upload into.
    :param fastq_paired: Map of paired-end fastq names to forward/reverse paths for files to upload.

    :return:  Map of fastq names to history ids in Galaxy for each file.
    """

    fastqs_to_upload={}
    paired_elements=[]

    for name in fastq_paired.iterkeys():
        entry=fastq_paired[name]
        forward=entry['forward']
        reverse=entry['reverse']

        fastqs_to_upload[name+'/forward']=forward
        fastqs_to_upload[name+'/reverse']=reverse
        
    fastq_history_ids=upload_fastqs_to_history_via_library(gi,history_id,library_id,fastqs_to_upload)

    # Convert to paired-end data structure
    for name in sorted(fastq_paired.iterkeys()):
        paired_elements.append(dataset_collections.CollectionElement(
            name=name,
            type='paired',
            elements=[
                dataset_collections.HistoryDatasetElement(name='forward', id=fastq_history_ids[name+'/forward']),
                dataset_collections.HistoryDatasetElement(name='reverse', id=fastq_history_ids[name+'/reverse'])
            ]
        ))
    
    return paired_elements

def upload_fastqs_library_single(gi,history_id,library_id,fastqs):
    """
    Uploads the given single-end fastq files to a Galaxy history via a dataset library.

    :param gi:  Galaxy instance.
    :param history_id:  History id to upload into.
    :param library_id:  Library id to upload into.
    :param fastqs: Map of single-end fastq names to 'single' paths for files to upload.

    :return:  Map of fastq names to history ids in Galaxy for each file.
    """

    fastqs_to_upload={}
    single_elements=[]

    for name in fastqs.iterkeys():
        fastqs_to_upload[name]=fastqs[name]['single']

    fastq_history_ids=upload_fastqs_to_history_via_library(gi,history_id,library_id,fastqs_to_upload)

    for name in sorted(fastqs.iterkeys()):
        single_elements.append(dataset_collections.HistoryDatasetElement(name=name,id=fastq_history_ids[name]))

    return single_elements

def upload_fastq_history_paired(gi,history_id,fastq_paired):
    """
    Uploads the given paired-end fastq files to a Galaxy history.

    :param gi:  Galaxy instance.
    :param history_id:  History id to upload into.
    :param fastqs: Map of paired-end fastq names to forward/reverse paths for files to upload.

    :return:  Map of fastq names to history ids in Galaxy for each file.
    """

    paired_elements=[]

    for name in sorted(fastq_paired.iterkeys()):
        entry=fastq_paired[name]
        forward=entry['forward']
        reverse=entry['reverse']
        
        print 'Uploading as copy '+forward
        forward_galaxy=gi.tools.upload_file(forward,history_id, file_type='fastqsanger')
        forward_id=forward_galaxy['outputs'][0]['id']
        print 'Uploading as copy '+reverse
        reverse_galaxy=gi.tools.upload_file(reverse,history_id, file_type='fastqsanger')
        reverse_id=reverse_galaxy['outputs'][0]['id']

        paired_elements.append(dataset_collections.CollectionElement(
            name=name,
            type='paired',
            elements=[
                dataset_collections.HistoryDatasetElement(name='forward', id=forward_id),
                dataset_collections.HistoryDatasetElement(name='reverse', id=reverse_id)
            ]
        ))

    return paired_elements

def upload_fastq_collection_paired(gi,history_id,fastq_paired):
    """
    Uploads given fastq files to the Galaxy history.

    :param gi:  Galaxy instance.
    :param history_Id:  History id to upload into.
    :param fastq_paired:  Paired-end files to upload.

    :return: The dataset collection id for the constructed dataset.
    """

    paired_elements=[]

    if (upload_fastqs_as_links):
        created_library=gi.libraries.create_library("SNVPhyl Library Dataset-"+str(time.time()))
        paired_elements=upload_fastqs_library_paired(gi,history_id,created_library['id'],fastq_paired)
    else:
        paired_elements=upload_fastq_history_paired(gi,history_id,fastq_paired)

    # construct paired collection
    paired_collection_name="paired_datasets"
    print "Building dataset collection named "+paired_collection_name
    collection_response_paired = gi.histories.create_dataset_collection(
        history_id=history_id,
        collection_description=dataset_collections.CollectionDescription(
            name=paired_collection_name,
            type="list:paired",
            elements=paired_elements
        )
    )

    return collection_response_paired['id']

def get_existing_fastq_collection(gi,fastq_history_name,collection_type):
    """
    Gets a valid fastq dataset collection from passed history name.

    :param gi:  Galaxy instance.
    :param fastq_dir:  Directory of fastq files.
    :param fastq_history_name:  History name for location of fastq files.
    :param collection_type:  Expected collection type of fastq file dataset collection.

    :return: A Galaxy fastq dataset collection from the history.
    """

    found_fastq_collection = None

    histories=gi.histories.get_histories(name=fastq_history_name)

    if (len(histories) == 0):
        raise Exception("Error: history with name '"+fastq_history_name+"' does not exist in Galaxy")
    elif (len(histories) > 1):
        raise Exception("Error: there are "+str(len(histories))+" histories with name '"+fastq_history_name+"'.  Please re-name appropriate history in Galaxy and try again")
    else:
        fastq_history=gi.histories.show_history(histories[0]['id'], contents=True)

        found_fastq_collection=None
        for dataset in fastq_history:
            if (dataset['history_content_type'] == 'dataset_collection' and dataset['collection_type'] == collection_type):
                if found_fastq_collection is not None:
                    raise Exception("Error: found collection "+dataset['name']+" but there already exists a collection "+found_fastq_collection['name']+" please remove unneeded collection and try again")
                else:
                    found_fastq_collection=dataset

    return found_fastq_collection

def validate_workflow(gi,snvphyl_workflow,workflow_settings,workflow_parameters):
    """
    Validate workflow in Galaxy against expected inputs and parameters.

    :param gi: Galaxy instance.
    :param snvphyl_exported_workflow: Workflow object returned from Galaxy bioblend get_workflows()
    :param workflow_settings: Settings XML object.

    :return: None
    :throws: Exception if the selected SNVPhyl workflow was invalid.
    """

    workflow_type=workflow_settings.attrib['type']
    if ('paired' in workflow_type):
        sequence_reads_name=workflow_settings.find('./inputs/sequenceReadsPaired').text
    elif ('single' in workflow_type):
        sequence_reads_name=workflow_settings.find('./inputs/sequenceReadsSingle').text
    else:
        raise Exception("Error: workflow_type="+workflow_type+" is neither paired-end or single-end")

    reference_name=workflow_settings.find('./inputs/reference').text

    if (len(gi.workflows.get_workflow_inputs(snvphyl_workflow['id'],sequence_reads_name)) == 0):
        raise Exception("Error: no sequence reads input with name '"+sequence_reads_name+"' in selected SNVPhyl workflow")
    if (len(gi.workflows.get_workflow_inputs(snvphyl_workflow['id'],reference_name)) == 0):
        raise Exception("Error: no reference input with name '"+reference_name+"' in given selected workflow")
    if ("invalid-positions" in workflow_type):
        invalid_positions_name=workflow_settings.find('./inputs/invalidPositions').text
        if (len(gi.workflows.get_workflow_inputs(snvphyl_workflow['id'],invalid_positions_name)) == 0):
            raise Exception("Error: no invalid positions input with name '"+invalid_positions_name+"' in selected SNVPhyl workflow")

    workflow_json=gi.workflows.export_workflow_json(snvphyl_workflow['id'])
    for tool_id in workflow_parameters:
        steps=find_workflow_steps(tool_id,workflow_json['steps'])
        if (len(steps) > 1):
            raise Exception("Error: multiple steps matching for tool '"+tool_id+"' "+steps)
        elif (len(steps) == 0):
            raise Exception("Error: no matching tool '"+tool_id+"' in SNVPhyl workflow")

        step=steps[0]
        workflow_params_json=json.loads(step['tool_state'])
        if (not verify_parameter_recursive(workflow_parameters[tool_id],workflow_params_json)):
            raise Exception("Error: parameter names to be set \n"+json.dumps(workflow_parameters[tool_id],indent=4,separators=(',', ': '))+"\n do not match those in selected SNVPhyl workflow \n"+json.dumps(workflow_params_json,indent=4,separators=(',', ': ')))
    
def verify_parameter_recursive(param,workflow_param):
    """
    Recursively checks parameters hash tables for equivalently named parameters.

    :param param:  The parameters set from the script.
    :param workflow_param:  Parameters from selected workflow.

    :return: True if all parameters in param are in workflow_param, false otherwise.
    """

    parameters_same=True
    for element in param:
        value=param[element]
        if (type(value) is dict):
            try:
                if (type(workflow_param[element]) is not dict):
                    workflow_sub_param=json.loads(workflow_param[element])
                else:
                    workflow_sub_param=workflow_param[element]
            except:
                parameters_same=False

            parameters_same = parameters_same and verify_parameter_recursive(value,workflow_sub_param)
        else:
            parameters_same = parameters_same and (element in workflow_param)

    return parameters_same

def select_workflow_type(is_paired_fastqs,has_invalid_positions):
    """
    Get workflow type given different types of data we are operating with.

    :param is_paired_fastqs: Whether or not we are using paired-end fastqs.
    :param has_invalid_positions:  Whether or not we have invalid positions.

    :return: A string of the workflow type.
    """
    if is_paired_fastqs:
        workflow_type = 'paired-end'
    else:
        workflow_type = 'single-end'

    if has_invalid_positions:
        workflow_type += '-invalid-positions'

    return workflow_type

# Adapted from http://stackoverflow.com/a/10609378
def wait_for_internet_connection(port):
    """
    Waits for a specific port to be free (that is, if Galaxy Docker is running).

    :param port:  The port to search for.

    :return: None.
    """
    sys.stdout.write("Waiting for docker to complete launching Galaxy on port "+str(port)+" ...")
    sys.stdout.flush()
    while True:
        try:
            response = urllib2.urlopen('http://localhost:'+str(port),timeout=5)
            print ".finished.  Galaxy in Docker has (hopefully) started successfully."
            return
        except Exception:
            sys.stdout.write(".")
            sys.stdout.flush()
            time.sleep(15)
            pass

def write_workflow_outputs(workflow_settings, run_name, gi, history_id, output_dir):
    """
    Gets workflow output files.

    :param :

    :return: None.
    """
    for output_name in workflow_settings.findall("./outputs/output[@name]"):
        try:
            file_pattern=output_name.attrib['fileName']
            file_name=str.replace(file_pattern,"${run_name}",run_name)
    
            print "Searching for dataset with name "+file_name
            file_datasets=gi.histories.show_matching_datasets(history_id,name_filter=file_name)
            if (len(file_datasets) == 0):
                raise Exception("Error: no matching datasets with name "+file_name)
            elif (len(file_datasets) > 1):
                raise Exception("Error: multiple datasets with name "+file_name)
            else:
                file_dataset=file_datasets[0]
                local_file_path=output_dir+"/"+file_name
                gi.datasets.download_dataset(file_dataset['id'],file_path=local_file_path,use_default_filename=False)
        except Exception, e:
            print >> sys.stderr, "Exception occured when downloading "+file_name+", skipping..."
            print >> sys.stderr, repr(e) + ": " + str(e)
            
def write_galaxy_provenance(gi,history_id,output_dir):
    """
    Writes provenance information from Galaxy to JSON output files.

    :param history_id:  The history id in Galaxy to examine.
    :param output_dir:  The directory to write the output files.

    :return: None.
    """

    histories_provenance_file=output_dir+"/history-provenance.json"
    dataset_provenance_file=output_dir+"/dataset-provenance.json"
    histories_prov_fh=open(histories_provenance_file,'w')
    dataset_prov_fh=open(dataset_provenance_file,'w')
    all_datasets=gi.histories.show_history(history_id,details='all',contents=True)
    dataset_content=[]
    for dataset in all_datasets:
        if (dataset['history_content_type'] == 'dataset'):
            dataset_content.append(gi.histories.show_dataset_provenance(history_id,dataset['id'],follow=True))
        elif (dataset['history_content_type'] == 'dataset_collection'):
            dataset_content.append(gi.histories.show_dataset_collection(history_id,dataset['id']))
        else:
            raise Exception("Error: dataset with id="+dataset['id']+" in history="+history_id+" has history_content_type="+dataset['history_content_type']+". Expected one of 'dataset' or 'dataset_collection'")
    dataset_prov_fh.write(json.dumps(dataset_content,indent=4,separators=(',', ': ')))
    histories_prov_fh.write(json.dumps(all_datasets,indent=4,separators=(',', ': ')))

    histories_prov_fh.close()
    dataset_prov_fh.close()

def run_snvphyl_workflow_newer_galaxy(gi,snvphyl_workflow_id,history_id,dataset_map,workflow_parameters,run_name):
    """
    Run SNVPhyl workflow with newer Galaxy API.

    :param snvphyl_workflow_id: ID of SNVPhyl workflow.
    :param history_id:  ID of history for workflow.
    :param dataset_map:  Map of input datasets in history.
    :param workflow_parameters:  Parameters for workflow.
    :param run_name:  Name of run for workflow.

    :return: None.
    """

    workflow_run=gi.workflows.invoke_workflow(
        workflow_id=snvphyl_workflow_id,
        history_id=history_id,
        inputs=dataset_map,
        params=workflow_parameters,
        import_inputs_to_history=True,
        replacement_params={
            'run_name': run_name
        }
    )

def run_snvphyl_workflow_older_galaxy(gi,snvphyl_workflow_id,history_id,dataset_map,workflow_parameters,run_name):
    """
    Run SNVPhyl workflow with older Galaxy API.

    :param snvphyl_workflow_id: ID of SNVPhyl workflow.
    :param history_id:  ID of history for workflow.
    :param dataset_map:  Map of input datasets in history.
    :param workflow_parameters:  Parameters for workflow.
    :param run_name:  Name of run for workflow.

    :return: None.
    """

    try:
        workflow_run=gi.workflows.run_workflow(
            workflow_id=snvphyl_workflow_id,
            history_id=history_id,
            dataset_map=dataset_map,
            params=workflow_parameters,
            import_inputs_to_history=True,
            replacement_params={
                'run_name': run_name
            }
        )
    except galaxy.client.ConnectionError as e:
        if ('Uncaught exception in exposed API method' in str(e)):
            print "Got exception '"+str(e)+"' but this type is expected with older Galaxy API even when the workflow is executed.  Will continue assuming this is the case.\n"
        else:
            raise e

def handle_deploy_docker(docker_port,with_docker_sudo,docker_cpus,snvphyl_version_settings,fastq_dir):
    """
    Deploys a Docker instance of Galaxy with the given snvphyl version workflow tools installed

    :param docker_port: Port to forward into Docker.
    :param with_docker_sudo: If true, prefix `sudo` to docker command.
    :param docker_cpus: Maximum number of CPUs docker should use.
    :param snvphyl_version_settings:  Settings for particular version of SNVPhyl to deploy.
    :param fastq_dir:  The input fastq direcory. If true, the directory will be mounted in docker under the directory in docker_fastq_dir.

    :return: A pair of (url,key. url and key are for the Galaxy instance in Docker.  Blocks until Galaxy is up and running. 
    """

    if ('dockerContainer' not in snvphyl_version_settings):
        raise Exception("Error: no docker container has been built for snvphyl version "+snvphyl_version_settings['version']+".  Cannot use --deploy-docker")

    docker_image=snvphyl_version_settings['dockerContainer']
    if (docker_image is None):
        raise Exception("Error: attempting to deploy Docker image for SNVPhyl "+snvphyl_version_settings['version']+" but no matching docker container")

    if (with_docker_sudo):
        docker_command_line = ['sudo']
    else:
        docker_command_line = []

    docker_command_line.extend(['docker','run'])

    if (docker_cpus > 0):
        docker_command_line.extend(['--cpus',str(docker_cpus),'--env','SLURM_CPUS='+str(docker_cpus)])

    docker_command_line.extend(['--detach','--publish',str(docker_port)+':80'])

    if (fastq_dir is not None):
        fastq_dir_abs = os.path.abspath(fastq_dir)
        docker_command_line.extend(['--volume',str(fastq_dir_abs)+':'+docker_fastq_dir])

    docker_command_line.append(docker_image)

    print "\nDeploying Docker Container"
    print "=========================="
    print "Running '"+" ".join(docker_command_line)+"'"
    docker_id=subprocess.check_output(docker_command_line).rstrip()
    print "Docker id "+docker_id

    wait_for_internet_connection(docker_port)

    return ("http://localhost:"+str(docker_port),'admin',docker_id)

def undeploy_docker_with_id(docker_id, with_docker_sudo):
    """
    Undeploys a docker instance

    :param docker_id: The id of the docker container to undeploy.
    """

    if (with_docker_sudo):
        docker_command_line = ['sudo']
    else:
        docker_command_line = []

    docker_command_line.extend(['docker','rm','-f','-v',docker_id])

    print "\nUndeploying and cleaning up Docker Container"
    print "============================================="
    print "Running '"+" ".join(docker_command_line)+"'"
    subprocess.call(docker_command_line)

def main(snvphyl_version_settings, galaxy_url, galaxy_api_key, deploy_docker, docker_port, docker_cpus, with_docker_sudo, keep_deployed_docker, snvphyl_version, workflow_id, fastq_dir, fastq_files_as_links, fastq_history_name, reference_file, run_name, 
         relative_snv_abundance, min_coverage, min_mean_mapping, repeat_minimum_length, repeat_minimum_pid, filter_density_window, filter_density_threshold, invalid_positions_file, output_dir):
    """
    The main method, wrapping around 'main_galaxy' to start up a docker image if needed.

    :param: The command-line parameters.

    :return: None.
    """

    global use_newer_galaxy_api
    global upload_fastqs_as_links
    global use_docker_fastq_dir

    docker_id=None

    if (not reference_file):
        raise Exception("Error: must specify a --reference-file")
    if (not output_dir):
        raise Exception("Error: must specify an --output-dir")

    upload_fastqs_as_links=fastq_files_as_links

    # if uploading as links, need to use aboslute path to files when sending to Galaxy
    if (upload_fastqs_as_links):
        fastq_dir=os.path.abspath(fastq_dir)

    if (deploy_docker and (galaxy_url or galaxy_api_key)):
        raise Exception("Error: cannot specify --galaxy-url and --galaxy-api-key along with --deploy-docker")
    elif (deploy_docker):

        if (fastq_dir is not None):
            upload_fastqs_as_links=True
            use_docker_fastq_dir=True

        # Older versions of Galaxy have bugs preventing usage of 'invoke_workflow" over 'run_workflow'
        # For up to date Docker images of Galaxy, we can gurantee newer version, so use newer API methods.
        # Otherwise, use older API methods, which throws confusing exceptions but still works.
        if LooseVersion(snvphyl_version) >= LooseVersion('1.0'):
            use_newer_galaxy_api=True

        if os.path.exists(output_dir):
            raise Exception("Error: output_dir="+output_dir+" exists")
        else:
            os.mkdir(output_dir)

        docker_begin_time=time.time()
        (url,key,docker_id)=handle_deploy_docker(docker_port,with_docker_sudo,docker_cpus,snvphyl_version_settings[snvphyl_version],fastq_dir)
        print "Took %0.2f minutes to deploy docker" % ((time.time()-docker_begin_time)/60)

        try:
            main_galaxy(url, key, snvphyl_version, workflow_id, fastq_dir, fastq_history_name, reference_file, run_name, relative_snv_abundance, min_coverage, min_mean_mapping,
                repeat_minimum_length, repeat_minimum_pid, filter_density_window, filter_density_threshold, invalid_positions_file, output_dir)
        finally:
            if (not keep_deployed_docker):
                undeploy_docker_with_id(docker_id, with_docker_sudo)
            else:
                print "Not undeploying docker.  Container id="+docker_id+", running on http://localhost:"+str(docker_port)+", with user=admin@galaxy.org, password=admin"

    elif (galaxy_url and galaxy_api_key):
        if os.path.exists(output_dir):
            raise Exception("Error: output_dir="+output_dir+" exists")
        else:
            os.mkdir(output_dir)

        main_galaxy(galaxy_url, galaxy_api_key, snvphyl_version, workflow_id, fastq_dir, fastq_history_name, reference_file, run_name, relative_snv_abundance, min_coverage, min_mean_mapping,
            repeat_minimum_length, repeat_minimum_pid, filter_density_window, filter_density_threshold, invalid_positions_file, output_dir)
    else:
        raise Exception("Error: must specify both --galaxy-url and --galaxy-api-key or --deploy-docker")


def main_galaxy(galaxy_url, galaxy_api_key, snvphyl_version, workflow_id, fastq_dir, fastq_history_name, reference_file, run_name, relative_snv_abundance, min_coverage, min_mean_mapping,
	repeat_minimum_length, repeat_minimum_pid, filter_density_window, filter_density_threshold, invalid_positions_file, output_dir):
    """
    The main method to interact with Galaxy and execute SNVPhyl.

    :param: The command-line parameters, minus those to set up docker.

    :return: None.
    """

    begin_time=time.time()
    fastq_dataset_collection=None
    is_paired_fastqs=False

    gi = galaxy.GalaxyInstance(url=galaxy_url, key=galaxy_api_key)

    print "\nExamining input fastq files"
    print "==========================="
    if (fastq_dir is None and fastq_history_name is None):
        raise Exception("Error: must set either --fastq-dir or --fastq-history-name")
    elif ((fastq_dir is not None) and (fastq_history_name is not None)):
        raise Exception("Error: cannot set both --fastq-dir and --fastq-history-name")
    elif (not fastq_history_name is None):
        fastq_dataset_collection_single=get_existing_fastq_collection(gi,fastq_history_name,'list')
        fastq_dataset_collection_paired=get_existing_fastq_collection(gi,fastq_history_name,'list:paired')

        if (fastq_dataset_collection_single and fastq_dataset_collection_paired):
            raise Exception("Error: collections "+fastq_dataset_collection_single['name']+" (list) and "+fastq_dataset_collection_paired['name']+" (list:paired) exist in same history "+fastq_history_name+".  Please remove one collection and try again")
        elif (fastq_dataset_collection_single):
            fastq_dataset_collection=fastq_dataset_collection_single
            if_paired_fastqs=False
        elif (fastq_dataset_collection_paired):
            fastq_dataset_collection=fastq_dataset_collection_paired
            is_paired_fastqs=True
        else:
            raise Exception("Error: Galaxy history "+fastq_history_name+" does not have a valid dataset collection of type 'list' or 'list:paired'. Please construct a collection of sequence read files and try again")
    else:
        (fastq_single,fastq_paired)=structure_fastqs(fastq_dir)
        if (fastq_single):
            is_paired_fastqs=False
        else:
            is_paired_fastqs=True

    workflow_type=select_workflow_type(is_paired_fastqs, invalid_positions_file != None)

    (workflow_settings,workflow_parameters)=load_snvphyl_settings(get_script_path()+"/../etc/snvphyl-settings.xml",snvphyl_version,workflow_type)

    print "\nSet up workflow input"
    print "====================="
    set_parameter_value(workflow_settings,workflow_parameters,'relative-snv-abundance',relative_snv_abundance)
    set_parameter_value(workflow_settings,workflow_parameters,'minimum-read-coverage',min_coverage)
    set_parameter_value(workflow_settings,workflow_parameters,'minimum-mean-mapping-quality',min_mean_mapping)
    set_parameter_value(workflow_settings,workflow_parameters,'repeat-minimum-length',repeat_minimum_length)
    set_parameter_value(workflow_settings,workflow_parameters,'repeat-minimum-pid',repeat_minimum_pid)
    set_parameter_value(workflow_settings,workflow_parameters,'filter-density-threshold',filter_density_threshold)
    set_parameter_value(workflow_settings,workflow_parameters,'filter-density-window-size',filter_density_window)
    
    if workflow_id is None:
        snvphyl_workflow=find_workflow_uuid(gi.workflows.get_workflows(), workflow_settings.attrib['uuid'])
        if (snvphyl_workflow is None):
            raise Exception('Error: no workflow in Galaxy '+galaxy_url+' with uuid='+workflow_settings.attrib['uuid'])
    else:
        results=gi.workflows.get_workflows(workflow_id=workflow_id)
        if len(results) == 0:
            raise Exception('Error: no workflow with id='+workflow_id)
        else:
            snvphyl_workflow=results[0]

    validate_workflow(gi,snvphyl_workflow,workflow_settings,workflow_parameters)

    reference_name=os.path.splitext(reference_file)[0]
    today = str(datetime.date.today())
    history_name='snvphyl-'+os.path.basename(reference_name)+'-'+today+'-'+run_name

    print "\nUpload files to Galaxy"
    print "======================"

    # create history
    print "Creating history in Galaxy name '"+history_name+"\'"
    created_history=gi.histories.create_history(history_name)
    history_id=created_history['id']

    # upload reference
    print "Uploading reference file "+reference_file
    reference_galaxy=gi.tools.upload_file(reference_file, history_id)
    reference_id=reference_galaxy['outputs'][0]['id']

    if (fastq_dataset_collection is None):
        # fastq files not in history, must upload them
        print "Uploading fastq files in history '"+history_name+"'"
        if (is_paired_fastqs):
            fastq_id=upload_fastq_collection_paired(gi,history_id,fastq_paired)
        else:
            fastq_id=upload_fastq_collection_single(gi,history_id,fastq_single)
    else:
        # fastq files already in Galaxy, get id of collection
        print "No need to upload files to Galaxy.  Using files from history named '"+fastq_history_name+"' and dataset collection '"+fastq_dataset_collection['name']+"'"
        fastq_id=fastq_dataset_collection['id']

    if invalid_positions_file != None:
        print "Uploading invalid positions file "+invalid_positions_file
        invalid_positions_galaxy=gi.tools.upload_file(invalid_positions_file, history_id)
        invalid_positions_id=invalid_positions_galaxy['outputs'][0]['id']

    print "Finished uploading data to history "+history_name

    if ('paired' in workflow_type):
        sequence_reads_name=workflow_settings.find('./inputs/sequenceReadsPaired').text
    elif ('single' in workflow_type):
        sequence_reads_name=workflow_settings.find('./inputs/sequenceReadsSingle').text
    else:
        raise Exception("Error: workflow_type="+workflow_type+" is neither paired-end or single-end")

    reference_name=workflow_settings.find('./inputs/reference').text
    fastq_input_id=gi.workflows.get_workflow_inputs(snvphyl_workflow['id'],sequence_reads_name)[0]
    reference_input_id=gi.workflows.get_workflow_inputs(snvphyl_workflow['id'],reference_name)[0]

    dataset_map={
        fastq_input_id: {'id': fastq_id, 'src': 'hdca'},
        reference_input_id: {'id': reference_id, 'src': 'hda'}
    }

    if invalid_positions_file != None:
        invalid_positions_name=workflow_settings.find('./inputs/invalidPositions').text
        invalid_positions_input_id=gi.workflows.get_workflow_inputs(snvphyl_workflow['id'],invalid_positions_name)[0]
        dataset_map[invalid_positions_input_id]={'id': invalid_positions_id, 'src': 'hda'}

    upload_end_time=time.time()

    output_settings_file=output_dir+'/run-settings.txt'
    settings_fh=open(output_settings_file,'w')
    settings_fh.write("#SNVPhyl Settings\n")
    settings_fh.write("snvphyl_cli_version=%s\n" % snvphyl_cli_version)
    settings_fh.write("snvphyl_cli_git_commit=%s\n" % get_git_commit())
    settings_fh.write("snvphyl_cli_command_line=%s\n" % get_command_line_string())
    settings_fh.write("snvphyl_version=%s\n" % snvphyl_version)
    settings_fh.write("workflow_type=%s\n" % workflow_type)
    if fastq_dir is not None:
        settings_fh.write("fastq_dir=%s\n" % fastq_dir)
    else:
        settings_fh.write("fastq_history_name=%s\n" % fastq_history_name)
        settings_fh.write("fastq_dataset_collection_name=%s\n" % fastq_dataset_collection['name'])
        settings_fh.write("fastq_dataset_collection_id=%s\n" % fastq_dataset_collection['id'])

    if invalid_positions_file != None:
        settings_fh.write("invalid_positions_file=%s\n" % invalid_positions_file)

    settings_fh.write("run_name=%s\n" % run_name)
    settings_fh.write("relative_snv_abundance=%s\n" % relative_snv_abundance)
    settings_fh.write("min_coverage=%s\n" % min_coverage)
    settings_fh.write("min_mean_mapping=%s\n" % min_mean_mapping)
    settings_fh.write("repeat_minimum_length=%s\n" % repeat_minimum_length)
    settings_fh.write("repeat_minimum_pid=%s\n" % repeat_minimum_pid)

    if LooseVersion(snvphyl_version) >= LooseVersion('1.0'):
        settings_fh.write("filter_density_window=%s\n" % filter_density_window)
        settings_fh.write("filter_density_threshold=%s\n" % filter_density_threshold)

    settings_fh.write("reference_file=%s\n" % reference_file)
    settings_fh.write("galaxy_url=%s\n" % galaxy_url)
    settings_fh.write("workflow_id=%s\n" % snvphyl_workflow['id'])
    settings_fh.write("workflow_name=%s\n" % snvphyl_workflow['name'])
    settings_fh.write("history_id=%s\n" % history_id)
    settings_fh.write("history_name=%s\n" % history_name)
    settings_fh.write("start_time=%s\n" % time.strftime("%Y-%m-%d %H:%M",time.localtime(begin_time)))
    settings_fh.write("upload_end_time=%s\n" % time.strftime("%Y-%m-%d %H:%M",time.localtime(upload_end_time)))
    settings_fh.write("upload_seconds=%i\n" % (upload_end_time - begin_time))
    settings_fh.flush()

    print "\nRunning workflow"
    print "================"

    print "Starting SNVPhyl version "+snvphyl_version+" type " + workflow_type + " workflow in history "+history_name
    if (use_newer_galaxy_api):
        run_snvphyl_workflow_newer_galaxy(gi,snvphyl_workflow['id'],history_id,dataset_map,workflow_parameters,run_name)
    else:
        run_snvphyl_workflow_older_galaxy(gi,snvphyl_workflow['id'],history_id,dataset_map,workflow_parameters,run_name)

    print "Workflow has started running in history " + history_name + " on Galaxy "+galaxy_url+" at "+time.strftime("%Y-%m-%d %H:%M")

    print "\nWaiting for workflow completion "
    print "==============================="

    workflow_complete=False
    sys.stdout.write("percent complete (can initially decrease as more jobs are scheduled by Galaxy): 0")
    sys.stdout.flush()
    time.sleep(60)
    while not workflow_complete:
        status=gi.histories.get_status(history_id)
        if (status['state_details']['error'] > 0):
            dataset_error_list=[]
            history_details=gi.histories.show_history(history_id,contents=True)
            for entry in history_details:
                if ('state' in entry and entry['state'] == 'error'):
                    dataset_error_list.append(entry['name'])

            print "\nError occured while running workflow, downloading existing output files\n"
            write_workflow_outputs(workflow_settings, run_name, gi, history_id, output_dir)
            print "\nWriting Galaxy provenance info\n"
            write_galaxy_provenance(gi,history_id,output_dir)
            raise Exception('error occured in workflow, history=['+history_name+'], problematic datasets=["'+'"; "'.join(dataset_error_list)+'"]')
        elif (status['state'] == 'ok'):
            workflow_complete=True
        else:
            sys.stdout.write("..."+str(status['percent_complete']))
            sys.stdout.flush()
            time.sleep(polling_time)

    print "\nWorkflow finished at "+time.strftime("%Y-%m-%d %H:%M")

    print "\nGetting workflow outputs"
    print "========================"
    write_workflow_outputs(workflow_settings, run_name, gi, history_id, output_dir)

    print "Getting provenance info from Galaxy"
    write_galaxy_provenance(gi,history_id,output_dir)

    end_time=time.time()
    settings_fh.write("end_time=%s\n" % time.strftime("%Y-%m-%d %H:%M",time.localtime(end_time)))
    settings_fh.write("workflow_seconds=%i\n" % (end_time - upload_end_time))
    settings_fh.write("total_seconds=%i\n" % (end_time - begin_time))
    settings_fh.close()

    print "\nFinished"
    print "========"
    print "Took %0.2f minutes" % ((end_time-begin_time)/60)
    print "Galaxy history "+history_id+" on "+galaxy_url
    print "Output in "+output_dir
    

### MAIN ###

if __name__ == '__main__':
    settings_file=get_script_path()+"/../etc/snvphyl-settings.xml"
    snvphyl_version_settings=get_all_snvphyl_versions(settings_file)
    versions=snvphyl_version_settings.keys()
    versions.sort(key=LooseVersion)
    current_version=versions.pop()

    available_versions = "SNVPhyl CLI: " + snvphyl_cli_version + "\nSNVPhyl CLI git commit: " + get_git_commit() + "\n\nAvailable SNVPhyl pipelines (--snvphyl-version):\n"
    for version in versions:
        available_versions += "\t"+version+"\n"
    available_versions += "\t"+current_version+" [default]\n"

    parser = argparse.ArgumentParser(description='Run the SNVPhyl workflow using the given Galaxy credentials and download results.',
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="\nExample:"+
               "\n  "+sys.argv[0]+" --deploy-docker --fastq-dir fastqs/ --reference-file reference.fasta --min-coverage 5 --output-dir output\n"+
               "\n    Runs default SNVPhyl pipeline in a Docker container with the given input files, setting the minimum coverage for calling a SNV to 5.\n\n"+
               "\n  "+sys.argv[0]+" --galaxy-url http://galaxy --galaxy-api-key 1234abcd --fastq-dir fastqs/ --reference-file reference.fasta --output-dir output\n"+
               "\n   Runs SNVPhyl pipeline against the given Galaxy server, with the given API key, and by uploading the passed fastq files and reference genome (assumes workflow has been uploaded ahead of time).\n"+
               "\n  "+sys.argv[0]+" --galaxy-url http://galaxy --galaxy-api-key 1234abcd --fastq-history-name fastq-history --reference-file reference.fasta --output-dir output\n"+
               "\n    Runs SNVPhyl pipeline against the given Galaxy server, with the given API key, using structured fastq data (paired or single dataset collections) from a history with the given name.\n\n")
    
    # Requires this argument to define Galaxy instance to execute pipeline within
    galaxy_api_group = parser.add_argument_group('Galaxy API (runs SNVPhyl in external Galaxy instance)')
    galaxy_api_group.add_argument('--galaxy-url', action="store", dest="galaxy_url",required=False, help='URL to the Galaxy instance to execute SNVPhyl')
    galaxy_api_group.add_argument(galaxy_api_key_name, action="store", dest="galaxy_api_key", required=False, help='API key for the Galaxy instance for executing SNVPhyl')

    # Or this argument to deply a particular Galaxy instance with Docker on the given port
    docker_group = parser.add_argument_group('Docker (runs SNVPhyl in local Docker container)')
    docker_group.add_argument('--deploy-docker', action="store_true", dest="deploy_docker", required=False, help='Deply an instance of Galaxy using Docker.')
    docker_group.add_argument('--keep-docker', action="store_true", dest="keep_deployed_docker", required=False, help='Keep docker image running after pipeline finishes.')
    docker_group.add_argument('--docker-port', action="store", dest="docker_port", default=48888, required=False, help='Port for deployment of Docker instance [48888].')
    docker_group.add_argument('--docker-cpus', action="store", type=int, dest="docker_cpus", default=-1, required=False, help='Limit on number of CPUs docker should use. The value -1 means use all CPUs available on the machine [-1]')
    docker_group.add_argument('--with-docker-sudo', action="store_true", dest="with_docker_sudo", required=False, help='Run `docker with `sudo` [False].')

    snvphyl_version_group = parser.add_argument_group('SNVPhyl Versions')
    snvphyl_version_group.add_argument('--snvphyl-version', action="store", dest="snvphyl_version", default=current_version, required=False, help='version of SNVPhyl to execute ['+current_version+'].')
    snvphyl_version_group.add_argument('--workflow-id', action="store", dest="workflow_id", required=False, help='Galaxy workflow id.  If not specified attempts to guess')

    input_group = parser.add_argument_group('Input')
    input_group.add_argument('--reference-file', action="store", dest="reference_file", required=False, help='Reference file (in .fasta format) to map reads to')

    output_group = parser.add_argument_group('Output')
    output_group.add_argument('--output-dir', action="store", dest="output_dir", required=False, help='Output directory to store results')

    # Requires either this argument for direct upload of fastq files
    input_group.add_argument('--fastq-dir', action="store", dest="fastq_dir", required=False, help='Directory of fastq files (ending in .fastq, .fq, .fastq.gz, .fq.gz). For paired-end data must be separated into files ending in _1/_2 or _R1/_R2 or _R1_001/_R2_001.')
    input_group.add_argument('--fastq-files-as-links', action="store_true", dest="fastq_files_as_links", required=False, help='Link to the fastq files in Galaxy instead of making copies.  This significantly speeds up SNVPhyl, but requires the Galaxy server to have direct access to fastq/ directory (e.g., same filesystem) and requires Galaxy to be configured with `allow_library_path_paste=True`. Usage of `--deploy-docker` enables this option by default [False]')
    # Or this argument for using already uploaded files
    input_group.add_argument('--fastq-history-name', action="store", dest="fastq_history_name", required=False, help='Galaxy history name for previously uploaded collection of fastq files.')

    #optional
    parameter_group = parser.add_argument_group("Optional Parameters")
    parameter_group.add_argument('--invalid-positions-file', action="store", dest="invalid_positions_file", required=False, help='Tab-delimited file of positions to mask on the reference.')
    parameter_group.add_argument('--run-name', action="store", dest="run_name", default="run", required=False, help='Name of run added to output files [run]')
    parameter_group.add_argument('--relative-snv-abundance', '--snv-abundance-ratio', '--alternative-allele-ratio', action="store", dest="relative_snv_abundance", default=0.75, required=False, help='Cutoff proportion of base coverage supporting a high quality variant to total coverage [0.75]')
    parameter_group.add_argument('--min-coverage', action="store", dest="min_coverage", default=10, required=False, help='Minimum coverage for calling variants [10]')
    parameter_group.add_argument('--min-mean-mapping', action="store", dest="min_mean_mapping", default=30, required=False, help='Minimum mean mapping quality for reads supporting a variant [30]')
    parameter_group.add_argument('--repeat-minimum-length', action="store", dest="repeat_minimum_length", default=150, required=False, help='Minimum length of repeat regions to remove [150]')
    parameter_group.add_argument('--repeat-minimum-pid', action="store", dest="repeat_minimum_pid", default=90, required=False, help='Minimum percent identity to identify repeat regions [90]')
    parameter_group.add_argument('--filter-density-window', action="store", dest="filter_density_window", default=500, required=False, help='Window size for identifying high-density SNV regions [500]')
    parameter_group.add_argument('--filter-density-threshold', action="store", dest="filter_density_threshold", default=2, required=False, help='SNV threshold for identifying high-density SNV regions [2]')

    info_group = parser.add_argument_group("Additional Information")
    info_group.add_argument('--version', action="version", version=available_versions)

    # print help with no arguments
    if len(sys.argv)==1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    dic = vars(args)

    main(snvphyl_version_settings, **dic)
