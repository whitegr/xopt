classdef Xopt < handle
  %XOPT Interface to Python Xopt optimization code
  % Requires:
  % * Matlab parallel computing toolbox
  % * Python, version compatible with installed Matlab: https://www.mathworks.com/help/matlab/matlab_external/install-supported-python-implementation.html
  % * Python Matlab Engine: https://www.mathworks.com/help/matlab/matlab_external/install-the-matlab-engine-for-python.html
  % * Xopt: https://github.com/ChristopherMayes/xopt and xopt module added to PYTHONPATH
  % *  -> including modules etc required by Xopt (see Xopt documentation)
  % * OpenMPI
  %
  % Useage:
  %  X = Xopt(funcname,x0,nobj) ;
  %    Associate objective function (funcname) to optimizer, this function must be in the function search path and have a number of input arguments equal t=o the length of x0 vector and nobj output arguments
  %    x0: initial point to evaluate objective function (dimensionality = number of decision variables)
  %    nobj: number of objectives
  %  X.runopt ;
  %  Results are in X.results
  %
  % e.g.
  %  X = Xopt("myobjfun",[0 0],2)
  %  With the following objective function:
  %  [y1,y2,c1] = function myobjfun(x1,x2)
  %  y1=  x1.^2 + x2.^2 - 1.0 - 0.1 * cos(16 .* atan2(x1, x2)) ;
  %  y2 = (x1 - 0.5).^2 + (x2 - 0.5).^2 ;
  %  c1=1; % use c1 to apply any constraint (constraint considered failed if c1<0)
  %  NB: If any outputs set to NaN or inf, then optimizer will skip this data point
  %
  % Currently supports the following algorithms within Xopt: MOBO
  properties
    PythonExe string = "python" % command line python executable
    Optimizer string {mustBeMember(Optimizer,"mobo")} = "mobo" % Optimizer routine supported by Xopt package
    Nworkers {mustBePositive} = 4
    verbose logical = false
    n_initial_samples {mustBePositive} = 5
    n_steps {mustBePositive} = 10
    batch_size {mustBePositive} = 5
  end
  properties(SetObservable)
    xrange = 1 % Allowable range for objective function input variables (must be scalar [use +/- this value for all] or [2,length(x0)])
    yrange = 1 % Allowable range for return variables from objective function (must be scalar [use +/- this value for all] or [2,nobj])
  end
  properties(SetAccess=private)
    fdir % directory containing objective function
    objfun
    x0 = 0 % starting variables for optimizer (dimensionality = number of decision variables)
    nobj = 1 % number of objectives (number of objective function return arguments)
    results % structure of results returned from optimizer: see Xopt documentation
    xopt_out % Captured command line output from Xopt execution
    xopt_stat % Status return from Xopt execution
  end
  properties(Access=private)
    pool
  end
  methods
    function obj = Xopt(funcname,x0,nobj)
      %XOPT
      %X = Xopt(functionhandle,x0,nobj)
      
      if nargin<3
        error('Incorrect arguments')
      end
      finfo = functions(str2func(funcname));
      if isempty(finfo.file)
        error('Objective function not found on path')
      end
      obj.objfun=funcname;
      d = dir(finfo.file);
      obj.fdir = d.folder ;
      obj.x0 = x0 ;
      obj.nobj=nobj;
    end
    function runopt(obj)
      %RUNOPT Run external Xopt optimizer
      % See results property for returned results data
      
      obj.results=[];
      
      % Ensure Matlab Engine(s) running (& initialize objective functions in workers)
      obj.StartEngine();
      
      % Pass on verbosity level to Xopt algorithm
      if obj.verbose; vtxt="True"; else; vtxt="False"; end
      
      % Write input files for Xopt run
      if length(obj.xrange)==1
        xran=[-ones(size(obj.x0)).*obj.xrange; ones(size(obj.x0)).*obj.xrange] ;
      else
        xran=obj.xrange;
      end
      if length(obj.yrange)==1
        yran=[-ones(1,obj.nobj).*obj.yrange; ones(1,obj.nobj).*obj.yrange] ;
      else
        yran=obj.yrange;
      end
      % Python file
      pyfile = fopen('xopt_eval.py','w') ;
      fprintf(pyfile,"import numpy as np\n");
      fprintf(pyfile,"from mpi4py import MPI\n");
      fprintf(pyfile,"comm = MPI.COMM_WORLD\n");
      fprintf(pyfile,"import matlab.engine\n\n");
      fprintf(pyfile,"names = matlab.engine.find_matlab()\n");
      str="BOUND_LOW, BOUND_UP = ";
      for ilim=1:2
        str=str+"[";
        for ix=1:length(obj.x0)
          str=str+"%g";
          if ix==length(obj.x0)
            str=str+"]";
          else
            str=str+", ";
          end
        end
        if ilim==2
          str=str+"\n\n";
        else
          str=str+", ";
        end
      end
      fprintf(pyfile,str,xran(1,:),xran(2,:));
      fprintf(pyfile,"X_RANGE = [%g, %g]\n",min(xran(:)),max(xran(:)));
      fprintf(pyfile,"Y_RANGE = [%g, %g]\n\n",min(yran(:)),max(yran(:)));
      fprintf(pyfile,"# labeled version\n");
      fprintf(pyfile,"def evaluate_func(inputs, matlab_f='xopt_fun', nargout=%d, verbose=%s):\n",obj.nobj,vtxt);
      fprintf(pyfile,"  info = {'some': 'info', 'about': ['the', 'run']}\n\n");
      str="  ";
      for ix=1:length(obj.x0)
        str=str+"x"+ix;
        if ix==length(obj.x0)
          str=str+" = ";
        else
          str=str+", ";
        end
      end
      for ix=1:length(obj.x0)
        str=str+"float(inputs['x"+ix+"'])";
        if ix==length(obj.x0)
          str=str+"\n\n";
        else
          str=str+", ";
        end
      end
      fprintf(pyfile,str);
      fprintf(pyfile,"  # Matlab wrapper\n");
      fprintf(pyfile,"  rank = comm.Get_rank()\n");
      fprintf(pyfile,"  eng_id = names[rank]\n");
      fprintf(pyfile,"  eng = matlab.engine.connect_matlab(eng_id)\n");
      fprintf(pyfile,"  f = getattr(eng, matlab_f)\n");
      str="  fval = f('"+obj.objfun+"',";
      for ix=1:length(obj.x0)
        str=str+"x"+ix+", ";
      end
      str=str+"nargout="+(obj.nobj+1)+")\n\n";
      fprintf(pyfile,str);
      fprintf(pyfile,"  # Bounds check\n");
      for ix=1:length(obj.x0)
        fprintf(pyfile,"  if x%d < BOUND_LOW[%d]:\n",ix,ix-1);
        fprintf(pyfile,"    raise ValueError(f'Input less than {BOUND_LOW[%d]} ')\n",ix-1);
        fprintf(pyfile,"  if x%d > BOUND_UP[%d]:\n",ix,ix-1);
        fprintf(pyfile,"    raise ValueError(f'Input greater than {BOUND_UP[%d]} ')\n",ix-1);
      end
      fprintf(pyfile,"\n  # Form outputs\n");
      str = "  outputs = {" ;
      for iy=1:obj.nobj
        str = str+sprintf("'y%d': fval[%d], ",iy,iy-1) ;
      end
      str = str+sprintf("\n    'c1': fval[%d]}\n\n",obj.nobj) ;
      fprintf(pyfile,str);
      fprintf(pyfile,"  return outputs\n");
      fclose(pyfile);
      % YAML File
      yfile = fopen('xopt_eval.yaml','w') ;
      fprintf(yfile,"xopt: {output_path: null, verbose: true}\n\n");
      fprintf(yfile,"algorithm:\n");
      fprintf(yfile,"  name: %s\n",obj.Optimizer);
      fprintf(yfile,"  options:\n");
      str="    ref: [";
      for ix=1:length(obj.x0)
        str=str+obj.x0(ix);
        if ix==length(obj.x0)
          str=str+"]\n";
        else
          str=str+", ";
        end
      end
      fprintf(yfile,str);
      fprintf(yfile,"    n_initial_samples: %d\n",obj.n_initial_samples);
      fprintf(yfile,"    n_steps: %d\n",obj.n_steps);
      fprintf(yfile,"    verbose: %s\n",vtxt);
      fprintf(yfile,"    generator_options:\n");
      fprintf(yfile,"      batch_size: %d\n\n",obj.batch_size);
      fprintf(yfile,"simulation:\n");
      fprintf(yfile,"  name: xopt_eval\n");
      fprintf(yfile,"  evaluate: xopt_eval.evaluate_func\n\n");
      fprintf(yfile,"vocs:\n");
      fprintf(yfile,"  name: xopt_eval\n");
      fprintf(yfile,"  description: null\n");
      fprintf(yfile,"  simulation: xopt_eval\n");
      fprintf(yfile,"  templates: null\n");
      fprintf(yfile,"  variables:\n");
      for ix=1:length(obj.x0)
        fprintf(yfile,"    x%d: [%g, %g]\n",ix,xran(1,ix),xran(2,ix));
      end
      fprintf(yfile,"  objectives:\n");
      for iy=1:obj.nobj
        fprintf(yfile,"    y%d: MINIMIZE\n",iy);
      end
      fprintf(yfile,"  constraints:\n");
      fprintf(yfile,"    c1: [GREATER_THAN, 0]\n");
      fprintf(yfile,"  linked_variables: {}\n");
      fprintf(yfile,"  constants: {a: dummy_constant}\n");
      fclose(yfile);
      
      % Execute optimization algorithm
      [stat,output] = system(sprintf("mpirun -n %d %s -m mpi4py.futures -m xopt.mpi.run xopt_eval.yaml",obj.Nworkers,obj.PythonExe));
      obj.xopt_out = output ;
      obj.xopt_stat = stat ;
      
      % Read results
      if stat==0
        obj.GetResults();
      else
        error('Error running Xopt:\n%s',output);
      end
      
    end
    function StartEngine(obj)
      %STARTENGINE Start Python matlab engine on parallel workers
      
      % Start workers or connect to already running pool
      if isempty(gcp('nocreate')) || (~isempty(obj.pool) && ~obj.pool.Connected)
        fprintf('Starting Matlab Engine on %d parallel worker nodes...\n',obj.Nworkers);
        obj.pool = parpool(obj.Nworkers) ;
      else
        obj.pool = gcp ;
        obj.Nworkers = obj.pool.NumWorkers ;
      end
      
      % Start Matlab Engine(s)
      spmd
        if ~matlab.engine.isEngineShared
          matlab.engine.shareEngine(sprintf('Engine_%d',labindex-1))
        end
      end
    end
    function StopEngine(obj)
      %STOPENGINE Stop Python matlab engine on parallel workers and shutdown worker pool
      if ~isempty(obj.pool)
        fprintf('Stopping Matlab Engine on all worker nodes and closing parallel pool...\n');
        delete(obj.pool);
        obj.pool=[];
      end
    end
    function RestartEngine(obj)
      %RESTARTENGINE Stop and then start Python matlab engine on parallel workers
      obj.StopEngine;
      obj.StartEngine;
    end
    function GetResults(obj)
      %GETRESULTS Read results from Xopt run
      if ~exist('results.json','file')
        error('No results exist');
      end
      fid = fopen('results.json');
      raw = fread(fid,inf);
      str = char(raw');
      fclose(fid);
      obj.results = jsondecode(str);
    end
  end
  % Set/Get methods
  methods
    function set.xrange(obj,val)
      if length(val)==1
        if val<0
          error('If scalar, must set > 0');
        end
      else
        if length(val)~=length(obj.x0) %#ok<MCSUP>
          error('Length of xrange must equal length of x0');
        end
      end
      obj.xrange=val;
    end
    function set.yrange(obj,val)
      if length(val)==1
        if val<0
          error('If scalar, must set > 0');
        end
      else
        if length(val)~=obj.nobj %#ok<MCSUP>
          error('Length of yrange must equal nobj');
        end
      end
      obj.yrange=val;
    end
  end
end