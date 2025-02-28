#!/usr/bin/env python3

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'junit-xml')))
from junit_xml import TestCase, TestSuite


def parse_testargs(file):
    if os.path.splitext(file)[1] in ['.c', '.cpp']:
        return sum([[[line.split()[1:], [line.split()[0].strip('//TESTARGS(name=').strip(')')]]]
                    for line in open(file).readlines()
                    if line.startswith('//TESTARGS')], [])
    elif os.path.splitext(file)[1] == '.usr':
        return sum([[[line.split()[1:], [line.split()[0].strip('C_TESTARGS(name=').strip(')')]]]
                    for line in open(file).readlines()
                    if line.startswith('C_TESTARGS')], [])
    elif os.path.splitext(file)[1] in ['.f90']:
        return sum([[[line.split()[1:], [line.split()[0].strip('C_TESTARGS(name=').strip(')')]]]
                    for line in open(file).readlines()
                    if line.startswith('! TESTARGS')], [])
    raise RuntimeError('Unrecognized extension for file: {}'.format(file))


def get_source(test):
    if test.startswith('petsc-'):
        return os.path.join('examples', 'petsc', test[6:] + '.c')
    elif test.startswith('mfem-'):
        return os.path.join('examples', 'mfem', test[5:] + '.cpp')
    elif test.startswith('nek-'):
        return os.path.join('examples', 'nek', 'bps', test[4:] + '.usr')
    elif test.startswith('fluids-'):
        return os.path.join('examples', 'fluids', test[7:] + '.c')
    elif test.startswith('solids-'):
        return os.path.join('examples', 'solids', test[7:] + '.c')
    elif test.startswith('ex'):
        return os.path.join('examples', 'ceed', test + '.c')
    elif test.endswith('-f'):
        return os.path.join('tests', test + '.f90')
    else:
        return os.path.join('tests', test + '.c')


def get_testargs(source):
    args = parse_testargs(source)
    if not args:
        return [(['{ceed_resource}'], [''])]
    return args


def check_required_failure(test_case, stderr, required):
    if required in stderr:
        test_case.status = 'fails with required: {}'.format(required)
    else:
        test_case.add_failure_info('required: {}'.format(required))


def contains_any(resource, substrings):
    return any((sub in resource for sub in substrings))


def skip_rule(test, resource):
    return any((
        test.startswith('t4') and contains_any(resource, ['occa']),
        test.startswith('t5') and contains_any(resource, ['occa']),
        test.startswith('ex') and contains_any(resource, ['occa']),
        test.startswith('mfem') and contains_any(resource, ['occa']),
        test.startswith('nek') and contains_any(resource, ['occa']),
        test.startswith('petsc-') and contains_any(resource, ['occa']),
        test.startswith('fluids-') and contains_any(resource, ['occa']),
        test.startswith('solids-') and contains_any(resource, ['occa']),
        test.startswith('t318') and contains_any(resource, ['/gpu/cuda/ref']),
        test.startswith('t506') and contains_any(resource, ['/gpu/cuda/shared']),
        ))


def run(test, backends, mode):
    import subprocess
    import time
    import difflib
    source = get_source(test)
    all_args = get_testargs(source)

    if mode.lower() == "tap":
        print('1..' + str(len(all_args) * len(backends)))

    test_cases = []
    my_env = os.environ.copy()
    my_env["CEED_ERROR_HANDLER"] = 'exit'
    index = 1
    for args, name in all_args:
        for ceed_resource in backends:
            rargs = [os.path.join('build', test)] + args.copy()
            rargs[rargs.index('{ceed_resource}')] = ceed_resource

            # run test
            if skip_rule(test, ceed_resource):
                test_case = TestCase('{} {}'.format(test, ceed_resource),
                                     elapsed_sec=0,
                                     timestamp=time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime()),
                                     stdout='',
                                     stderr='')
                test_case.add_skipped_info('Pre-run skip rule')
            else:
                start = time.time()
                proc = subprocess.run(rargs,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE,
                                      env=my_env)
                proc.stdout = proc.stdout.decode('utf-8')
                proc.stderr = proc.stderr.decode('utf-8')

                test_case = TestCase('{} {} {}'.format(test, *name, ceed_resource),
                                     classname=os.path.dirname(source),
                                     elapsed_sec=time.time() - start,
                                     timestamp=time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(start)),
                                     stdout=proc.stdout,
                                     stderr=proc.stderr)
                ref_stdout = os.path.join('tests/output', test + '.out')

            # check for allowed errors
            if not test_case.is_skipped() and proc.stderr:
                if 'OCCA backend failed to use' in proc.stderr:
                    test_case.add_skipped_info('occa mode not supported {} {}'.format(test, ceed_resource))
                elif 'Backend does not implement' in proc.stderr:
                    test_case.add_skipped_info('not implemented {} {}'.format(test, ceed_resource))
                elif 'Can only provide HOST memory for this backend' in proc.stderr:
                    test_case.add_skipped_info('device memory not supported {} {}'.format(test, ceed_resource))
                elif 'Test not implemented in single precision' in proc.stderr:
                    test_case.add_skipped_info('not implemented {} {}'.format(test, ceed_resource))

            # check required failures
            if not test_case.is_skipped():
                if test[:4] in 't006 t007'.split():
                    check_required_failure(test_case, proc.stderr, 'No suitable backend:')
                if test[:4] in 't008'.split():
                    check_required_failure(test_case, proc.stderr, 'Available backend resources:')
                if test[:4] in 't110 t111 t112 t113 t114'.split():
                    check_required_failure(test_case, proc.stderr, 'Cannot grant CeedVector array access')
                if test[:4] in 't115'.split():
                    check_required_failure(test_case, proc.stderr, 'Cannot grant CeedVector read-only array access, the access lock is already in use')
                if test[:4] in 't116'.split():
                    check_required_failure(test_case, proc.stderr, 'Cannot destroy CeedVector, the writable access lock is in use')
                if test[:4] in 't117'.split():
                    check_required_failure(test_case, proc.stderr, 'Cannot restore CeedVector array access, access was not granted')
                if test[:4] in 't118'.split():
                    check_required_failure(test_case, proc.stderr, 'Cannot sync CeedVector, the access lock is already in use')
                if test[:4] in 't215'.split():
                    check_required_failure(test_case, proc.stderr, 'Cannot destroy CeedElemRestriction, a process has read access to the offset data')
                if test[:4] in 't303'.split():
                    check_required_failure(test_case, proc.stderr, 'Length of input/output vectors incompatible with basis dimensions')
                if test[:4] in 't408'.split():
                    check_required_failure(test_case, proc.stderr, 'CeedQFunctionContextGetData(): Cannot grant CeedQFunctionContext data access, a process has read access')
                if test[:4] in 't409'.split() and contains_any(ceed_resource, ['memcheck']):
                    check_required_failure(test_case, proc.stderr, 'Context data changed while accessed in read-only mode')

            # classify other results
            if not test_case.is_skipped() and not test_case.status:
                if proc.stderr:
                    test_case.add_failure_info('stderr', proc.stderr)
                elif proc.returncode != 0:
                    test_case.add_error_info('returncode = {}'.format(proc.returncode))
                elif os.path.isfile(ref_stdout):
                    with open(ref_stdout) as ref:
                        diff = list(difflib.unified_diff(ref.readlines(),
                                                         proc.stdout.splitlines(keepends=True),
                                                         fromfile=ref_stdout,
                                                         tofile='New'))
                    if diff:
                        test_case.add_failure_info('stdout', output=''.join(diff))
                elif proc.stdout and test[:4] not in 't003':
                    test_case.add_failure_info('stdout', output=proc.stdout)

            # store result
            test_case.args = ' '.join(rargs)
            test_cases.append(test_case)

            if mode.lower() == "tap":
                # print incremental output if TAP mode
                print('# Test: {}'.format(test_case.name.split(' ')[1]))
                print('# $ {}'.format(test_case.args))
                if test_case.is_error():
                    print('not ok {} - ERROR: {}'.format(index, test_case.errors[0]['message'].strip()))
                    print(test_case.errors[0]['output'].strip())
                elif test_case.is_failure():
                    print('not ok {} - FAIL: {}'.format(index, test_case.failures[0]['message'].strip()))
                    print(test_case.failures[0]['output'].strip())
                elif test_case.is_skipped():
                    print('ok {} - SKIP: {}'.format(index, test_case.skipped[0]['message'].strip()))
                else:
                    print('ok {} - PASS'.format(index))
                sys.stdout.flush()
            else:
                # print error or failure information if JUNIT mode
                if test_case.is_error():
                    print('Test: {} {}'.format(test_case.name.split(' ')[0], test_case.name.split(' ')[1]))
                    print('ERROR: {}'.format(test_case.errors[0]['message'].strip()))
                    print(test_case.errors[0]['output'].strip())
                elif test_case.is_failure():
                    print('Test: {} {}'.format(test_case.name.split(' ')[0], test_case.name.split(' ')[1]))
                    print('FAIL: {}'.format(test_case.failures[0]['message'].strip()))
                    print(test_case.failures[0]['output'].strip())
                sys.stdout.flush()
            index += 1

    return TestSuite(test, test_cases)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser('Test runner with JUnit and TAP output')
    parser.add_argument('--mode', help='Output mode, JUnit or TAP', default="JUnit")
    parser.add_argument('--output', help='Output file to write test', default=None)
    parser.add_argument('--gather', help='Gather all *.junit files into XML', action='store_true')
    parser.add_argument('test', help='Test executable', nargs='?')
    args = parser.parse_args()

    if args.gather:
        gather()
    else:
        backends = os.environ['BACKENDS'].split()

        # run tests
        result = run(args.test, backends, args.mode)

        # build output
        if args.mode.lower() == "junit":
            junit_batch = ''
            try:
                junit_batch = '-' + os.environ['JUNIT_BATCH']
            except:
                pass
            output = (os.path.join('build', args.test + junit_batch + '.junit')
                      if args.output is None
                      else args.output)

            with open(output, 'w') as fd:
                TestSuite.to_file(fd, [result])
        elif args.mode.lower() != "tap":
            raise Exception("output mode not recognized")

        # check return code
        for t in result.test_cases:
            failures = len([c for c in result.test_cases if c.is_failure()])
            errors = len([c for c in result.test_cases if c.is_error()])
            if failures + errors > 0 and args.mode.lower() != "tap":
                sys.exit(1)
