"use strict";

/*
* make an http request to make an allocation for the current user
*
* @param {targetid} str -> target to acquire
*
* return {void} -> it reloads the windows though
*/
async function acquire(targetid) {
    let r = await fetch('/ttb-v2/allocation', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
            'groups': {
                targetid: [targetid]
            },
            'queue': true,
            "endtime": 'static',
      })
    });

    let b = await r.text();

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }

    if (r.status != 200) {
        alert(b);
        return
    }

    window.location.reload()
}

/*
* releases target based on an allocation id
*
* @param {allocid} str -> allocation id that you want to remove
*
* return {void} -> it reloads the windows though
*/
async function js_alloc_remove(allocid) {
    let r = await fetch('/ttb-v2/allocation/' + allocid, {
      method: 'DELETE',
    });

    let b = await r.text();

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }

    if (r.status != 200) {
        alert(b);
        return
    }

    window.location.reload()
}

/*
* make a power call given an action and a component
*
* @param {targetid} str -> target for performing power action
* @param {action} str -> on/off/cycle, action you want to perform
* @param {component} str -> component we want to perform the action onto
*
* return {void}
*/
async function power(targetid, action, component) {
    $('.diagnostics').empty();
    $('#loading').append(
        '<label>power ' + action + ': ' + component+ ' </label><progress id="progress-bar" aria-label="Content loading…"></progress></div>' +
        '<br>'
    );

    // https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/power/on
    let data = new URLSearchParams();

    if (component != 'all') {
        data.append('component', component);
    }

    let r = await fetch('/ttb-v2/targets/' + targetid + '/power/' + action, {
        method: 'PUT',
        body: data,
    });

    let b = await r.text();

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }

    if (!r.ok) {
        alert(
            'something went wrong: ' + b
        );
        $('#loading').empty();
        $('#loading').append(
            '<b><label style="color: red;">FAIL</label></b>'
        );
        window.location.reload();
        return
    }


    $('#loading').empty();
    $('#loading').append(
        '<b><label style="color: green;">SUCCESS</label></b>'
    );

    window.location.reload()
}


/*
 * make a button call given an action and a component
 *
 * FIXME: this iss exactly the same as for power; refactor adding an interface name
 *
 * @param {targetid} str -> target for performing power action
 * @param {action} str -> on/off/cycle, action you want to perform
 * @param {component} str -> component we want to perform the action onto
 *
 * return {void}
 */
async function js_buttons(targetid, action, component) {
    $('.diagnostics').empty();
    $('#loading').append(
        '<label>' + component + ': ' + action + ' </label><progress id="progress-bar" aria-label="Content loading…"></progress></div>' +
        '<br>'
    );

    // https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/buttons/on
    let data = new URLSearchParams();

    if (component != 'all') {
        data.append('component', component);
    }

    let r = await fetch('/ttb-v2/targets/' + targetid + '/buttons/' + action, {
        method: 'PUT',
        body: data,
    });

    let b = await r.text();

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }

    if (!r.ok) {
        alert(
            'something went wrong: ' + b
        );
        $('#loading').empty();
        $('#loading').append(
            '<b><label style="color: red;">FAIL</label></b>'
        );
        window.location.reload();
        return
    }


    $('#loading').empty();
    $('#loading').append(
        '<b><label style="color: green;">SUCCESS</label></b>'
    );

    window.location.reload()
}

function common_error_check(r) {

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return true
    }

    if (!r.ok) {
        alert(
            'something went wrong: ' + response_text
        );
        $('#loading').empty();
        $('#loading').append(
            '<b><label style="color: red;">FAIL</label></b>'
        );
        window.location.reload();
        return true
    }

    return false
}


/*
* Remove a guest from an allocation
*
* @param {allocid} str -> allocation from which to remove the guest
* @param {selector_id} str -> select tag html id which selected the user
*
* return {void}
*/
async function js_alloc_guest_add(allocid, input_field_id) {

    $('.diagnostics').empty();

    // the selector_id element in the HTML document has picked up something
    let input_field_item = document.getElementById(input_field_id);
    console.log('DEBUG 1')
    if (input_field_item == null) {
        // this means do nothing
        return
    }
    console.log('DEBUG 2')
    let user_name = input_field_item.value;

    console.log('DEBUG user_name is ' + user_name)

    let r = await fetch('/ttb-v2/allocation/' + allocid + '/' + user_name, {
        method: 'PATCH',
    });

    if (common_error_check(r)) {
        return
    }

    $('#loading').empty();
    $('#loading').append(
        '<b><label style="color: green;">SUCCESS</label></b>'
    );

    window.location.reload()
}


/*
* Remove a guest from an allocation
*
* @param {allocid} str -> allocation from which to remove the guest
* @param {selector_id} str -> select tag html id which selected the user
*
* return {void}
*/
async function js_alloc_guest_remove(allocid, selector_id) {

    $('.diagnostics').empty();

    // the selector_id element in the HTML document has picked up something
    let selected_item = document.getElementById(selector_id);
    if (selected_item == null) {
        // this means do nothing
        return
    }
    let user_name = selected_item.value;

    if (user_name.value == 'None') {
        // this means do nothing
        return
    }

    let r = await fetch('/ttb-v2/allocation/' + allocid + '/' + user_name, {
        method: 'DELETE',
    });

    if (common_error_check(r)) {
        return
    }

    $('#loading').empty();
    $('#loading').append(
        '<b><label style="color: green;">SUCCESS</label></b>'
    );

    window.location.reload()
}



/*
* make a flashing call given a version and an image type
*
* @param {targetid} str -> target id to which you want to flash
* @param {select_id} str -> select tag html id where the paths for flashing are
* @param {image_type} str ->  the type of firmware you want to flash, if you
*   want to flash multiple you can separate them by `:`
*   Ex. fw:bios:ifwi:
* @param {suffix} str ->  suffix, if any, of the image files name names , you
*   can send multiple separated by `:`
*   Ex. ::.img:
*
* return {void}
*/
async function js_images_flash(targetid, select_id, image_type, suffix) {

    // jquery does not like dots in ids, we need to escape them
    select_id = select_id.replace('.', '\\.');

    let selected = document.getElementById(select_id);
    let fullpath = selected.value;
    $('#loading').append(
        '<label>flashing ' + image_type + ': ' + fullpath + ' </label><progress id="progress-bar" aria-label="Content loading…"></progress></div>' +
        '<br>'
    );

    let images = new Object();
    if (select_id != 'flash_images_version_for_all') {
        images[image_type] = fullpath;
    } else {
        // flashing multiple images bios:fw:smth:
        const imgs = image_type.split(':');
        const suffixes = suffix.split(':');
        imgs.pop()
        suffixes.pop()

        let i = 0;
        imgs.forEach((img_type) => {
            images[img_type] = fullpath + img_type + suffixes[i];
            i++;
        });
    }

    images = JSON.stringify(images);

    let data = new URLSearchParams();
    data.append('images', images);

    // https://<SERVER>:5000/ttb-v2/targets/<TARGET NAME>/images/flash
    //  -X PUT-d images='{"bios":"bios.xz"}'
    let r = await fetch('/ttb-v2/targets/' + targetid + '/images/flash', {
        method: 'PUT',
        body: data,
    });

    let response_text = await r.text();

    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }

    if (!r.ok) {
        alert(
            'something went wrong: ' + response_text
        );
        $('#loading').empty();
        $('#loading').append(
            '<b><label style="color: red;">FAIL</label></b>'
        );
        window.location.reload();
        return
    }


    $('#loading').empty();
    $('#loading').append(
        '<b><label style="color: green;">SUCCESS</label></b>'
    );

    window.location.reload()
}

/**
 * toggle visibilty of div
 *
 * modify html element by id, switching the display tag to either, show the
 * element or hide it.
 *
 * @param {id} var      id of element you want to toggle.
 *
 * @return {void}
 */
function toggle(id) {
    let inv  = document.getElementById(id);
    if (inv.style.display === "none") {
        inv.style.display = "block";
        return;
    }
    inv.style.display = "none";
}


/**
 * make inventory dialog appear
 *
 * @return {void}
 */
function show_inventory() {
    const inventory = document.getElementById('inventory');
    inventory.showModal();
}


/*
 * Create a terminal and make a loop calling `terminal_get_content` every n
 * (200) miliseconds
 *
 * @param {div_id} str  -> div id where you want to terminal created
 * @param {targetid} str -> target id from where you read consoles
 * @param {terminal} str -> name console you want to enable
 *
 * @return {void}
 *
 */
function terminal_create(div_id, targetid, terminal) {

    /* clean div, in case there is already a terminal there*/
    $('#' + div_id).empty();

    /* create new terminal, here we can specify the terminal configuration, we
     * also add a message telling the user that the console has been enabled */
    let term = new window.Terminal({
        cursorBlink: true,
        fontFamily: 'monospace',
        convertEol: true
    });
    term.open(document.getElementById(div_id));
    term.write('\x1b[37;40m \n\r\r\nconsole was started;\r\r\n\n\x1b[0m');
    term.onData(async function(data) {
        await terminal_send_keystroke(targetid, terminal, data);
    });

    /* here we loop calling the terminal_get_content function every n
     * miliseconds */
    let bytes_read_so_far = 0;
    let terminal_generation = 0;
    setInterval(async function() {

        let read_information_d = await terminal_get_content(
            term, targetid, terminal, bytes_read_so_far);

        let tmp_terminal_generation = read_information_d['stream-gen-offset'].split(' ')[0];
        let max_bytes_read = read_information_d['stream-gen-offset'].split(' ')[1];

        let bytes_label = document.getElementById('console-read-bytes-' + terminal);
        let generation_label = document.getElementById('console-generation-' + terminal);

        /* compare new terminal generation to old one if it changed the
         * terminal was disable and enabled since our last request so we need
         * to reset everything */
        if (tmp_terminal_generation != terminal_generation) {
            if (terminal_generation != 0) {
                term.write('\x1b[37;40m \n\r\r\nWARNING: console was restarted;\r\r\n\n\x1b[0m');
            }
            terminal_generation = tmp_terminal_generation;
            generation_label.textContent = terminal_generation;
            bytes_read_so_far = 0;
            return
        }

        /* check if what we got from the response is 0, if it is it means we
         * are up to date, no need to do anything, let's just make sure the
         * label `bytes_read` says the correct amount and try the next
         * iteration */
        if(read_information_d['content-length'] == 0) {
            bytes_read_so_far = parseInt(max_bytes_read);
            bytes_label.textContent = bytes_read_so_far;
            return
        }

        /*
         * we read the amount of bytes we have from the label bytes_label in
         * the html,  we then sum the length of the last request, this gives us
         * the number of bytes we have actually read
         */
        bytes_read_so_far = parseInt(bytes_label.textContent);
        bytes_read_so_far += parseInt(read_information_d['content-length']);
        bytes_label.textContent = bytes_read_so_far;

    }, 300);
}


/*
 * Make a http request to the server to read the console.
 *
 * You can specify may specify an offset if needed to. Go to ttbl/console.py
 * for more info
 *
 * @param {term} window.Terminal -> object created by xterm, this is the
 *      terminal object where you want to write the content
 * @param {targetid} str -> target id from where you read consoles
 * @param {terminal} str -> name console you want to enable
 * @param {offset} int -> offset you want to read the terminal from. Go to
 *      ttbl/console.py for more info
 *
 * @return {dict} -> {
 *      'content-length': content_length,
 *      'stream-gen-offset': generation
 *  }
 *
 *  content-length:str: is the content length of the bytes received, we get
 *  this from the response header
 *
 *  stream-gen-offset:list: two elements, first is the generation of the
 *  terminal (go to ttbl/consoles.py for more info), the second one is the max
 *  ammount of bytes available in  that terminal.
 *
 */
async function terminal_get_content(term, targetid, terminal, offset) {
    // curl -sk cookies.txt -k -X GET https://SERVERNAME:5000/ttb-v2/targets/TARGETNAME/console/read \
    // -d component=ssh0 -d offset=10
    let r = await fetch('/ttb-v2/targets/' + targetid + '/console/' + 'read?' + new URLSearchParams({
        'component': terminal,
        'offset': offset,
    }));

    let b = await r.text();
    term.write(b);

    let content_length = r.headers.get('Content-Length');
    let generation = r.headers.get('X-Stream-Gen-Offset');

    return {
        'content-length': content_length,
        'stream-gen-offset': generation
    }
}


/**
 * Send a keystroke/string as an http request to an specified console.
 *
 * This is called by func:terminal_create`
 *      term.onData(async function(data) {
 *          await terminal_send_keystroke(targetid, terminal, data);
 *      });
 *
 * This basically adds a listener to the terminal and will pass any char the
 * user sends.
 *
 * Got the idea from here http://hostiledeveloper.com/2017/05/02/something-useless-terminal-in-your-browser.html
 *
 * @param {targetid} str -> target id from where you want to send the string to
 * @param {terminal} str -> name console you want to send the string to
 * @param {keystroke} str -> string you want to send to the terminal
 *
 * @return {void}
 */
async function terminal_send_keystroke(targetid, terminal, keystroke) {

    let data = new URLSearchParams();
    data.append('component', terminal);
    keystroke = keystroke.toString()

    if (/^[0-9]*$/.test(keystroke)) {
        // the keystroke is a number, we need to add the '"' to not trip the
        // js and have him send a integer
        data.append('data', '\"' + keystroke + '\"');
    } else {
        data.append('data', keystroke);
    }
    let r = await fetch('/ttb-v2/targets/' + targetid + '/console/write', {
        method: 'PUT',
        body: data,
    });
    let b = await r.text();
    if (r.status != 200) {
        /* FIXME we need to add a better way to display this type of messages
         * to the user, so we do not rely on alerts */
        alert(
            'ERROR: could not write to the terminal. Due to: ' + '\n' + b
        );
        return
    }
}


/**
 * Enable or disable a console given its name and targetid
 *
 * @param {targetid} str -> target id from where you want enable/disable the
 *      consoles
 * @param {terminal} str -> name console you want to enable
 * @param {enable} str -> what action you want to perform in the console, just
 *      this two options: enable/disable
 *
 * @return {void}
 */
async function js_console_enable(targetid, terminal, enable) {
    let data = new URLSearchParams();
    data.append('component', terminal);

    let r = await fetch('/ttb-v2/targets/' + targetid + '/console/' + enable, {
      method: 'PUT',
      body: data,
    });

    let b = await r.text();
    if (r.status != 200) {
        alert(
            'there was an issue enabling or disabling the console:' +
            terminal + '\n' + b
        );
        return
    }

    /* FIXME we need to add a better way to display this type of messages to
     * the user, so we do not rely on alerts */
    alert('SUCCESS; ' + terminal + ' ' + enable + 'd');
}


/*
 * As the name states, this function will get (given a targetid) the power
 * state of all the components in the power rail. It will also update the table
 * where the power components are, this can be done because the state of each
 * component is in a datacell with the id 'table-datacell-{{component}}-state'
 *
 * So we can quickly identify each cell based on the response of the http
 * request /power/list.
 *
 * @param {targetid} str -> target id you want to read the power components
 *                          from
 *
 * return {void}
 */
async function power_state_update_for_all_components(targetid) {
    $('#loading').append(
        '<label>refreshing state of the power rail:<br></label><progress id="progress-bar" aria-label="Content loading…"></progress></div>' +
        '<br>'
    );
    let r = await fetch('/ttb-v2/targets/' + targetid + '/power/list');
    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }
    let body = await r.text();
    if (r.status != 200) {
        alert('there was an error reading the state of the power rail\n' + body);
        return
    }
    let power_list = JSON.parse(body);
    let power_rail = power_list['components'];
    for (const [component, information] of Object.entries(power_rail)) {
        let table_datacell = document.getElementById('table-datacell-' + component + '-state');
        if (information['state'] === false) {
            table_datacell.textContent = 'off';
            table_datacell.style.color = 'red';
        } else {
            table_datacell.textContent = 'on';
            table_datacell.style.color = 'green';
        }
    }
    $('#loading').empty();
}


/*
 * As the name states, this function will get (given a targetid) the buttons
 * state of all the components in the button/jumper/relay rail. It will also
 * update the table where the buttons components are, this can be done because
 * the state of each component is in a datacell with the id
 * 'table-datacell-{{component}}-button-state'
 *
 * So we can quickly identify each cell based on the response of the http
 * request /buttons/list.
 *
 * @param {targetid} str -> target id you want to read the power components
 *                          from
 *
 * return {void}
 */
async function buttons_state_update_for_all_components(targetid) {
    $('#loading').append(
        '<label>refreshing state of the buttons:<br></label><progress id="progress-bar" aria-label="Content loading…"></progress></div>' +
        '<br>'
    );
    let r = await fetch('/ttb-v2/targets/' + targetid + '/buttons/list');
    if (r.status == 401) {
        alert(
            'oops, seems that you are not logged in. Please log in to' +
            ' acquire machines (top right corner)'
        );
        return
    }
    let body = await r.text();
    if (r.status != 200) {
        alert('there was an error reading the state of the buttons rail\n' + body);
        return
    }
    let buttons_list = JSON.parse(body);
    let buttons_rail = buttons_list['components'];
    for (const [component, information] of Object.entries(buttons_rail)) {
        let table_datacell = document.getElementById('table-datacell-' + component + '-button-state');
        if (information['state'] === false) {
            table_datacell.textContent = 'off';
            table_datacell.style.color = 'red';
        } else {
            table_datacell.textContent = 'on';
            table_datacell.style.color = 'green';
        }
    }
    $('#loading').empty();
}

