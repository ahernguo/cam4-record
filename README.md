> This project is for practice purposes only.
> do not distribute the video footage! 
> Violators shall bear their own legal responsibilities

# Summary

This project is use to recording CAM4 videos behind the screen.
No live image will be displayed

# Usage

1. install [python3](https://www.python.org/downloads/)
    * I'm using `3.6.15`
2. download this repo. or use `git clone https://github.com/ahernguo/cam4-record.git`
3. `cd cam4-record` to this repo directory
4. install requirements

    `pip install -r requirements.txt`

5. edit `setting.json`. for example

    ```json
    "out_dir": "E:\\Cam4" /* the directory to save video */,
    "wanted": [
       "person_1",
       "person_2"
    ] /* list of cam4's username that want to record */
    ```

6. start monitoring

   `python main.py`

7. done.

    > you may create a windows schedule for execute it when computer starts.