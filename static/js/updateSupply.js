///////////////////////////////////////////////
// Code for "Update" buttons on dashboard
///////////////////////////////////////////////


// Get ALL the update buttons!
var update_buttons = $(".update-item");

// State variable; we'll use this to decide whether the user has begun updating
// or is done updating.
var updating = false;
var prevButtonID;


// Add an event listener to all the update buttons to get the id and send it
// to the server. Each button id corresponds to an item in the db.
update_buttons.on("click", function(evt) {

    // Prepare selector strings derived from button id.
    var buttonID = $(this).attr("id");
    var buttonSelector = "#" + buttonID+".update-item";
    var col = "#"+buttonID+".qty-column";
    var field = "#"+buttonID+".qty-field";

    // If we weren't previously updating, change the text of the button so
    // the user knows to press it agani when finished. Show a text field
    // for the user to type in.
    if (updating === false) {
        $(buttonSelector).html("Done!");
        updating = true;
        prevButtonID = buttonID;
        $(field).toggle();
    }

    // If we were previously updating, then the user is done. Send the item id
    // and the new quantity to the server, hide the text field, update
    // the quantity text in the column.
    else if (updating === true) {

        if (buttonID != prevButtonID) {
            evt.preventDefault();
            var prevCol = "#"+prevButtonID+".qty-column";
            $(prevCol).html(" <i>Please finish with this update first.</i>");
        }

        else if ($.isNumeric($(field).val()) || ($(field).val() === "")) {
            updating = false;
            $.post("/update-item", {"qty": $(field).val(), "itemID": buttonID}, function(data) {
                $(field).toggle();
                $(col).html(data);

                // If the qty was 0, then the supply should have been deleted. 
                // Hide the update button to prevent the user from trying to update
                // again.
                if (data === "Deleted!") {
                    $(buttonSelector).hide();
                    $(col).html("<div id='deleted' style='color:red'><i>Deleted!</i></div>");
                }

                else {
                    $(buttonSelector).html("Update Stock");
                    $(col).append('<div id="success" style="color:green"><i>Successfully updated!</i></div>');
                    $("#success").fadeOut(1000);
                }
            });

            // Remake the chart in the image of our new data. All hail the database,
            // source of truth.
            $.get("/supply-types", function(newSupplyData) {
                $('#donutChart').remove();
                $("#donutLegend").remove();
                $("#supply-type-chart").append('<canvas id="donutChart"></canvas>');
                contextForDonut = $("#donutChart").get(0).getContext("2d");
                var inventoryChart = new Chart(contextForDonut, {
                                                label: "Supplies by Quantity",
                                                type: 'doughnut',
                                                data: newSupplyData,
                                                options: options
                                              });
                $('#donutLegend').html(inventoryChart.generateLegend());
            });
        }

        else {
            evt.preventDefault();
            $(col).append(" <i>Please enter a number.</i>");
        }
    }

});